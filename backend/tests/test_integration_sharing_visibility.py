import asyncio
from uuid import UUID

from api.routes import auth


class _FakeExecuteResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _FakeSession:
    def __init__(self):
        self.executed = []
        self.committed = False

    async def execute(self, query, params=None):
        self.executed.append((str(query), params))
        return _FakeExecuteResult(len(self.executed))

    async def commit(self):
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_sharing_visibility_propagates_to_activities_and_meetings(monkeypatch):
    integration_id = UUID("11111111-1111-1111-1111-111111111111")
    owner_user_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    session = _FakeSession()

    monkeypatch.setattr(auth, "get_admin_session", lambda: _FakeSessionContext(session))

    asyncio.run(
        auth._propagate_integration_synced_data_visibility(
            integration_id,
            share_synced_data=False,
            owner_user_id=owner_user_id,
        )
    )

    assert session.committed
    assert len(session.executed) == 2
    assert "UPDATE activities" in session.executed[0][0]
    assert "visibility IS DISTINCT FROM" in session.executed[0][0]
    assert session.executed[0][1] == {"vis": "owner_only", "iid": integration_id}
    assert "UPDATE meetings" in session.executed[1][0]
    assert "visibility IS DISTINCT FROM" in session.executed[1][0]
    assert "owner_user_id = CASE" in session.executed[1][0]
    assert "owner_user_id IS DISTINCT FROM" in session.executed[1][0]
    assert session.executed[1][1] == {
        "vis": "owner_only",
        "iid": integration_id,
        "owner_user_id": owner_user_id,
    }


def test_sharing_visibility_propagates_team_visibility(monkeypatch):
    integration_id = UUID("22222222-2222-2222-2222-222222222222")
    owner_user_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    session = _FakeSession()

    monkeypatch.setattr(auth, "get_admin_session", lambda: _FakeSessionContext(session))

    asyncio.run(
        auth._propagate_integration_synced_data_visibility(
            integration_id,
            share_synced_data=True,
            owner_user_id=owner_user_id,
        )
    )

    assert [params["vis"] for _query, params in session.executed] == ["team", "team"]
    assert session.executed[1][1]["owner_user_id"] == owner_user_id
