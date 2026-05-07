import asyncio
from types import SimpleNamespace
from uuid import uuid4

from connectors import google_calendar
from connectors.google_calendar import GoogleCalendarConnector


class _FakeSession:
    def __init__(self, meeting):
        self.meeting = meeting
        self.added = []
        self.commits = 0

    async def get(self, model, _identifier):
        if model.__name__ == "User":
            return SimpleNamespace(email="owner@example.com")
        if model.__name__ == "Meeting":
            return self.meeting
        return None

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_create_huddle_refetches_meeting_with_owner_rls_context(monkeypatch):
    org_id = str(uuid4())
    owner_user_id = str(uuid4())
    integration_id = uuid4()
    meeting_id = uuid4()
    refetched_meeting = SimpleNamespace(id=meeting_id)
    session = _FakeSession(refetched_meeting)
    get_session_calls = []

    def fake_get_session(**kwargs):
        get_session_calls.append(kwargs)
        return _FakeSessionContext(session)

    async def fake_make_meet_request(*_args, **_kwargs):
        return {
            "name": "spaces/abc123",
            "meetingUri": "https://meet.google.com/abc-defg-hij",
            "meetingCode": "abc-defg-hij",
        }

    async def fake_find_or_create_meeting(**kwargs):
        assert kwargs["owner_user_id"] == owner_user_id
        assert kwargs["visibility"] == "owner_only"
        return SimpleNamespace(id=meeting_id)

    monkeypatch.setattr(google_calendar, "get_session", fake_get_session)
    monkeypatch.setattr(google_calendar, "find_or_create_meeting", fake_find_or_create_meeting)

    connector = GoogleCalendarConnector(organization_id=org_id, user_id=owner_user_id)
    connector._integration = SimpleNamespace(
        id=integration_id,
        user_id=owner_user_id,
        share_synced_data=False,
    )
    monkeypatch.setattr(connector, "_make_meet_request", fake_make_meet_request)

    result = asyncio.run(connector._action_create_huddle({"title": "Private huddle"}))

    assert result["status"] == "ok"
    assert refetched_meeting.conference_link == "https://meet.google.com/abc-defg-hij"
    assert refetched_meeting.huddle_status == "active"
    assert session.added[0].owner_user_id == owner_user_id
    assert session.added[0].visibility == "owner_only"
    assert get_session_calls == [
        {"organization_id": org_id, "user_id": owner_user_id},
        {"organization_id": org_id, "user_id": owner_user_id},
    ]
