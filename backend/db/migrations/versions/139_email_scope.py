"""Restrict email activity visibility for non-global admins.

Revision ID: 139_email_scope
Revises: 138_users_self_update
Create Date: 2026-05-07
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "139_email_scope"
down_revision: Union[str, None] = "138_users_self_update"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMPTY_UUID: str = "00000000-0000-0000-0000-000000000000"

_CURRENT_ORG_ID: str = f"""
COALESCE(
    NULLIF(current_setting('app.current_org_id', true), ''),
    '{_EMPTY_UUID}'
)::uuid
""".strip()

_CURRENT_USER_ID: str = f"""
COALESCE(
    NULLIF(current_setting('app.current_user_id', true), ''),
    '{_EMPTY_UUID}'
)::uuid
""".strip()

_ORG_MATCH: str = f"activities.organization_id = {_CURRENT_ORG_ID}"

_EMAIL_IS_OWNED_BY_CURRENT_USER: str = (
    f"activities.owner_user_id = {_CURRENT_USER_ID}"
)

_EMAIL_SHARED_BY_OWNER_INTEGRATION: str = """
EXISTS (
    SELECT 1
    FROM integrations i
    WHERE i.id = activities.integration_id
      AND i.organization_id = activities.organization_id
      AND i.user_id = activities.owner_user_id
      AND i.is_active = TRUE
      AND i.share_synced_data = TRUE
)
""".strip()

_LEGACY_ACTIVITY_VISIBLE: str = f"""
activities.visibility = 'team'
OR activities.owner_user_id IS NULL
OR activities.owner_user_id = {_CURRENT_USER_ID}
""".strip()

_ACTIVITY_VISIBLE: str = f"""
current_app_user_is_global_admin()
OR (
    activities.type = 'email'
    AND (
        {_EMAIL_IS_OWNED_BY_CURRENT_USER}
        OR {_EMAIL_SHARED_BY_OWNER_INTEGRATION}
    )
)
OR (
    COALESCE(activities.type, '') <> 'email'
    AND ({_LEGACY_ACTIVITY_VISIBLE})
)
""".strip()

_POLICY_BODY: str = f"""
({_ORG_MATCH})
AND (
    {_ACTIVITY_VISIBLE}
)
""".strip()

_LEGACY_POLICY_BODY: str = f"""
({_ORG_MATCH})
AND (
    {_LEGACY_ACTIVITY_VISIBLE}
)
""".strip()


def upgrade() -> None:
    assert len(revision) <= 32
    assert isinstance(down_revision, str) and len(down_revision) <= 32

    op.execute("DROP POLICY IF EXISTS org_and_user_isolation ON activities")
    op.execute(f"""
        CREATE POLICY org_and_user_isolation ON activities
        FOR ALL
        USING ({_POLICY_BODY})
        WITH CHECK ({_POLICY_BODY})
        """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_and_user_isolation ON activities")
    op.execute(f"""
        CREATE POLICY org_and_user_isolation ON activities
        FOR ALL
        USING ({_LEGACY_POLICY_BODY})
        WITH CHECK ({_LEGACY_POLICY_BODY})
        """)
