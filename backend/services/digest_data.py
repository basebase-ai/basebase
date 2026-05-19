"""
Collect per-member activity for a calendar day (America/Los_Angeles).

Used by the collect_digest_data agent tool and nightly digest workflows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select

from models.activity import Activity
from models.external_identity_mapping import ExternalIdentityMapping
from models.github_commit import GitHubCommit
from models.github_pull_request import GitHubPullRequest
from models.meeting import Meeting
from models.organization import Organization
from models.shared_file import SharedFile
from models.tracker_issue import TrackerIssue
from models.user import User

_PT: ZoneInfo = ZoneInfo("America/Los_Angeles")

DIGEST_NAMESPACE: str = "daily_digest"


def digest_date_yesterday_pt(*, now_utc: datetime | None = None) -> date:
    """Calendar 'yesterday' in America/Los_Angeles."""
    now: datetime = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_pt: datetime = now.astimezone(_PT)
    return now_pt.date() - timedelta(days=1)


def pt_calendar_day_utc_naive_bounds(d: date) -> tuple[datetime, datetime]:
    """Start (inclusive) and end (exclusive) of calendar day *d* in PT, as naive UTC datetimes."""
    start_pt: datetime = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=_PT)
    end_pt: datetime = start_pt + timedelta(days=1)
    start_utc: datetime = start_pt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc: datetime = end_pt.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def _normalize_email(e: str | None) -> str | None:
    if e is None:
        return None
    stripped: str = e.strip().lower()
    return stripped if stripped else None


async def _load_identity_blobs(
    session: Any,
    organization_id: UUID,
    user_id: UUID,
) -> tuple[list[str], list[str], list[str]]:
    """Slack user IDs, GitHub logins, lowercase emails from mappings + user row."""
    slack_ids: list[str] = []
    github_logins: list[str] = []
    emails: set[str] = set()

    u_result = await session.execute(select(User).where(User.id == user_id))
    user: User | None = u_result.scalar_one_or_none()
    if user and user.email:
        ne: str | None = _normalize_email(user.email)
        if ne:
            emails.add(ne)

    m_result = await session.execute(
        select(ExternalIdentityMapping).where(
            ExternalIdentityMapping.organization_id == organization_id,
            ExternalIdentityMapping.user_id == user_id,
        )
    )
    mappings: list[ExternalIdentityMapping] = list(m_result.scalars().all())
    for m in mappings:
        src: str = (m.source or "").lower()
        if m.external_userid:
            if src == "slack":
                slack_ids.append(str(m.external_userid))
            elif src == "github":
                github_logins.append(str(m.external_userid))
        for em in (m.external_email, m.revtops_email):
            ne2: str | None = _normalize_email(em)
            if ne2:
                emails.add(ne2)

    return slack_ids, github_logins, sorted(emails)


async def collect_member_raw_data(
    session: Any,
    organization_id: UUID,
    user_id: UUID,
    digest_date: date,
) -> dict[str, Any]:
    """Gather structured raw rows for LLM input."""
    start_naive: datetime
    end_naive: datetime
    start_naive, end_naive = pt_calendar_day_utc_naive_bounds(digest_date)

    slack_ids: list[str]
    github_logins: list[str]
    email_list: list[str]
    slack_ids, github_logins, email_list = await _load_identity_blobs(
        session, organization_id, user_id
    )

    u_result = await session.execute(select(User).where(User.id == user_id))
    user_row: User | None = u_result.scalar_one_or_none()
    member_name: str = (user_row.name or "").strip() if user_row else ""

    org_result = await session.execute(
        select(Organization.name).where(Organization.id == organization_id)
    )
    org_name: str = (org_result.scalar_one_or_none() or "").strip()

    raw: dict[str, Any] = {
        "digest_date": digest_date.isoformat(),
        "member_name": member_name,
        "org_name": org_name,
        "slack_user_ids": slack_ids,
        "github_logins": github_logins,
        "emails": email_list,
        "activities": [],
        "meetings": [],
        "tracker_issues": [],
        "github_commits": [],
        "github_pull_requests": [],
        "shared_files": [],
    }

    act_filters: list[Any] = [
        Activity.organization_id == organization_id,
        Activity.activity_date.is_not(None),
        Activity.activity_date >= start_naive,
        Activity.activity_date < end_naive,
    ]
    owner_parts: list[Any] = [
        Activity.owner_user_id == user_id,
        Activity.created_by_id == user_id,
    ]
    if slack_ids:
        slack_or: list[Any] = [
            Activity.custom_fields.contains({"user_id": sid}) for sid in slack_ids
        ]
        owner_parts.append(
            and_(Activity.source_system == "slack", or_(*slack_or)),
        )
    act_stmt = (
        select(Activity)
        .where(and_(*act_filters, or_(*owner_parts)))
        .order_by(Activity.activity_date.desc())
        .limit(200)
    )
    act_rows = await session.execute(act_stmt)
    for a in act_rows.scalars().all():
        raw["activities"].append(
            {
                "source_system": a.source_system,
                "type": a.type,
                "subject": (a.subject or "")[:500],
                "description": (a.description or "")[:500],
                "activity_date": a.activity_date.isoformat() if a.activity_date else None,
            }
        )

    meet_stmt = select(Meeting).where(
        Meeting.organization_id == organization_id,
        Meeting.scheduled_start >= start_naive,
        Meeting.scheduled_start < end_naive,
    ).limit(100)
    meet_rows = await session.execute(meet_stmt)
    email_set: set[str] = set(email_list)
    for m in meet_rows.scalars().all():
        matched: bool = False
        if email_set and m.participants:
            for p in m.participants:
                if not isinstance(p, dict):
                    continue
                em: str | None = _normalize_email(str(p.get("email") or ""))
                if em and em in email_set:
                    matched = True
                    break
        if m.organizer_email:
            oem: str | None = _normalize_email(m.organizer_email)
            if oem and oem in email_set:
                matched = True
        if matched:
            raw["meetings"].append(
                {
                    "title": m.title,
                    "scheduled_start": m.scheduled_start.isoformat() if m.scheduled_start else None,
                    "status": m.status,
                    "summary": (m.summary or "")[:800],
                }
            )

    issue_user_filter: list[Any] = [TrackerIssue.user_id == user_id]
    if email_list:
        issue_user_filter.append(TrackerIssue.assignee_email.in_(email_list))
    issue_stmt = (
        select(TrackerIssue)
        .where(
            TrackerIssue.organization_id == organization_id,
            or_(*issue_user_filter),
            or_(
                and_(
                    TrackerIssue.completed_date.is_not(None),
                    TrackerIssue.completed_date >= start_naive,
                    TrackerIssue.completed_date < end_naive,
                ),
                and_(
                    TrackerIssue.updated_date.is_not(None),
                    TrackerIssue.updated_date >= start_naive,
                    TrackerIssue.updated_date < end_naive,
                    TrackerIssue.state_type == "completed",
                ),
            ),
        )
        .order_by(TrackerIssue.updated_date.desc().nulls_last())
        .limit(80)
    )
    issue_rows = await session.execute(issue_stmt)
    for iss in issue_rows.scalars().all():
        raw["tracker_issues"].append(
            {
                "identifier": iss.identifier,
                "title": iss.title[:300],
                "state_type": iss.state_type,
                "state_name": iss.state_name,
                "url": iss.url,
            }
        )

    gh_user_filter: list[Any] = [GitHubCommit.user_id == user_id]
    if email_list:
        gh_user_filter.append(GitHubCommit.author_email.in_(email_list))
    if github_logins:
        gh_user_filter.append(GitHubCommit.author_login.in_(github_logins))
    gc_stmt = (
        select(GitHubCommit)
        .where(
            GitHubCommit.organization_id == organization_id,
            GitHubCommit.author_date >= start_naive,
            GitHubCommit.author_date < end_naive,
            or_(*gh_user_filter),
        )
        .order_by(GitHubCommit.author_date.desc())
        .limit(80)
    )
    for c in (await session.execute(gc_stmt)).scalars().all():
        raw["github_commits"].append(
            {
                "sha": c.sha[:12],
                "message": (c.message or "")[:400],
                "author_date": c.author_date.isoformat() if c.author_date else None,
                "url": c.url,
            }
        )

    pr_user_filter: list[Any] = [GitHubPullRequest.user_id == user_id]
    if github_logins:
        pr_user_filter.append(GitHubPullRequest.author_login.in_(github_logins))
    pr_date_or: list[Any] = [
        and_(
            GitHubPullRequest.merged_date.is_not(None),
            GitHubPullRequest.merged_date >= start_naive,
            GitHubPullRequest.merged_date < end_naive,
        ),
        and_(
            GitHubPullRequest.created_date >= start_naive,
            GitHubPullRequest.created_date < end_naive,
        ),
    ]
    gpr_stmt = (
        select(GitHubPullRequest)
        .where(
            GitHubPullRequest.organization_id == organization_id,
            or_(*pr_user_filter),
            or_(*pr_date_or),
        )
        .order_by(GitHubPullRequest.updated_date.desc().nulls_last())
        .limit(80)
    )
    for pr in (await session.execute(gpr_stmt)).scalars().all():
        raw["github_pull_requests"].append(
            {
                "number": pr.number,
                "title": pr.title[:300],
                "state": pr.state,
                "merged_date": pr.merged_date.isoformat() if pr.merged_date else None,
                "created_date": pr.created_date.isoformat() if pr.created_date else None,
                "url": pr.url,
            }
        )

    sf_stmt = (
        select(SharedFile)
        .where(
            SharedFile.organization_id == organization_id,
            SharedFile.user_id == user_id,
            or_(
                and_(
                    SharedFile.source_modified_at.is_not(None),
                    SharedFile.source_modified_at >= start_naive,
                    SharedFile.source_modified_at < end_naive,
                ),
                and_(
                    SharedFile.synced_at.is_not(None),
                    SharedFile.synced_at >= start_naive,
                    SharedFile.synced_at < end_naive,
                ),
            ),
        )
        .limit(60)
    )
    for sf in (await session.execute(sf_stmt)).scalars().all():
        raw["shared_files"].append(
            {
                "name": sf.name[:300],
                "source": sf.source,
                "mime_type": sf.mime_type,
            }
        )

    _source_systems_seen: set[str] = set()
    for a in raw["activities"]:
        ss: str = str(a.get("source_system", ""))
        if ss:
            _source_systems_seen.add(ss)
    if raw["meetings"]:
        _source_systems_seen.add("meetings")
    if raw["tracker_issues"]:
        _source_systems_seen.add("linear")
    if raw["github_commits"] or raw["github_pull_requests"]:
        _source_systems_seen.add("github")
    if raw["shared_files"]:
        _source_systems_seen.add("google_drive")
    raw["active_sources"] = sorted(_source_systems_seen)

    return raw
