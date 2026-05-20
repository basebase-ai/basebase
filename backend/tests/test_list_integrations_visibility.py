import asyncio
from types import SimpleNamespace
from uuid import UUID

from api.routes import auth


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, integrations, team_members):
        self._integrations = integrations
        self._team_members = team_members
        self._execute_calls = 0

    async def execute(self, _query):
        self._execute_calls += 1
        if self._execute_calls == 1:
            return _ScalarResult(self._integrations)
        if self._execute_calls == 2:
            return _ScalarResult(self._team_members)
        raise AssertionError("Unexpected execute call")


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_list_integrations_includes_team_connected_provider_as_connected(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    current_user_id = UUID("22222222-2222-2222-2222-222222222222")
    teammate_id = UUID("33333333-3333-3333-3333-333333333333")

    teammate_integration = SimpleNamespace(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        connector="gmail",
        organization_id=org_id,
        user_id=teammate_id,
        is_active=True,
        last_sync_at=None,
        last_error=None,
        created_at=None,
        share_synced_data=True,
        share_query_access=True,
        share_write_access=False,
        pending_sharing_config=False,
        sync_stats={"activities": 12},
        account_identifier="teammate@gmail.com",
        account_label="Teammate Gmail",
        extra_data={"account_avatar_url": "https://example.com/avatar.png"},
    )

    teammate_user = SimpleNamespace(id=teammate_id, name="Teammate", email="teammate@example.com")

    fake_session = _FakeSession([teammate_integration], [teammate_user])
    monkeypatch.setattr(auth, "get_session", lambda **kwargs: _FakeSessionContext(fake_session))
    monkeypatch.setattr(auth, "_get_scope_by_provider", lambda: {"gmail": "user"})
    monkeypatch.setattr(auth, "PROVIDER_SHARING_DEFAULTS", {"gmail": {}})

    result = asyncio.run(
        auth.list_integrations(
            auth=auth.AuthContext(
                user_id=current_user_id,
                organization_id=org_id,
                email="requester@example.com",
                role="member",
                is_global_admin=False,
            ),
        )
    )

    gmail_rows = [row for row in result.integrations if row.provider == "gmail"]
    assert len(gmail_rows) == 1
    gmail_row = gmail_rows[0]

    assert gmail_row.current_user_connected is False
    assert gmail_row.is_active is True
    assert gmail_row.team_connections
    assert gmail_row.team_connections[0].user_name == "Teammate"
    assert gmail_row.account_identifier == "teammate@gmail.com"
    assert gmail_row.id == str(teammate_integration.id)


def test_list_integrations_team_rep_ignores_non_team_rows(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    current_user_id = UUID("22222222-2222-2222-2222-222222222222")
    teammate_id = UUID("33333333-3333-3333-3333-333333333333")
    former_member_id = UUID("99999999-9999-9999-9999-999999999999")

    non_team_integration = SimpleNamespace(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        connector="gmail",
        organization_id=org_id,
        user_id=former_member_id,
        is_active=True,
        last_sync_at=None,
        last_error=None,
        created_at=None,
        share_synced_data=True,
        share_query_access=True,
        share_write_access=True,
        pending_sharing_config=False,
        sync_stats={"activities": 99},
        account_identifier="former@example.com",
        account_label="Former Member Gmail",
        extra_data={"account_avatar_url": "https://example.com/former.png"},
    )
    teammate_integration = SimpleNamespace(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        connector="gmail",
        organization_id=org_id,
        user_id=teammate_id,
        is_active=True,
        last_sync_at=None,
        last_error=None,
        created_at=None,
        share_synced_data=True,
        share_query_access=True,
        share_write_access=False,
        pending_sharing_config=False,
        sync_stats={"activities": 12},
        account_identifier="teammate@gmail.com",
        account_label="Teammate Gmail",
        extra_data={"account_avatar_url": "https://example.com/avatar.png"},
    )

    teammate_user = SimpleNamespace(id=teammate_id, name="Teammate", email="teammate@example.com")

    fake_session = _FakeSession([non_team_integration, teammate_integration], [teammate_user])
    monkeypatch.setattr(auth, "get_session", lambda **kwargs: _FakeSessionContext(fake_session))
    monkeypatch.setattr(auth, "_get_scope_by_provider", lambda: {"gmail": "user"})
    monkeypatch.setattr(auth, "PROVIDER_SHARING_DEFAULTS", {"gmail": {}})

    result = asyncio.run(
        auth.list_integrations(
            auth=auth.AuthContext(
                user_id=current_user_id,
                organization_id=org_id,
                email="requester@example.com",
                role="member",
                is_global_admin=False,
            ),
        )
    )

    gmail_row = [row for row in result.integrations if row.provider == "gmail"][0]
    assert gmail_row.id == str(teammate_integration.id)
    assert gmail_row.account_identifier == "teammate@gmail.com"
