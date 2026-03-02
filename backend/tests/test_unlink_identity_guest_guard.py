import asyncio
from types import SimpleNamespace
from uuid import UUID

from api.routes import auth


class _FakeSession:
    def __init__(self, requester, mapping, linked_user):
        self.requester = requester
        self.mapping = mapping
        self.linked_user = linked_user
        self.committed = False

    async def get(self, _model, model_id):
        if model_id == self.requester.id:
            return self.requester
        if model_id == self.mapping.id:
            return self.mapping
        if self.linked_user and model_id == self.linked_user.id:
            return self.linked_user
        return None

    async def commit(self):
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_unlink_identity_rejects_guest_linked_mapping(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    requester_id = UUID("22222222-2222-2222-2222-222222222222")
    mapping_id = UUID("33333333-3333-3333-3333-333333333333")
    guest_user_id = UUID("44444444-4444-4444-4444-444444444444")

    requester = SimpleNamespace(id=requester_id, organization_id=org_id)
    mapping = SimpleNamespace(
        id=mapping_id,
        organization_id=org_id,
        user_id=guest_user_id,
        revtops_email="guest@acme.com",
        match_source="admin_manual_link",
    )
    linked_user = SimpleNamespace(id=guest_user_id, is_guest=True)

    fake_session = _FakeSession(requester, mapping, linked_user)
    monkeypatch.setattr(auth, "get_session", lambda: _FakeSessionContext(fake_session))

    try:
        asyncio.run(
            auth.unlink_identity(
                org_id=str(org_id),
                request=auth.UnlinkIdentityRequest(mapping_id=str(mapping_id)),
                user_id=str(requester_id),
            )
        )
        raise AssertionError("Expected HTTPException")
    except auth.HTTPException as exc:
        assert exc.status_code == 403
        assert "Guest user identities" in exc.detail

    assert mapping.user_id == guest_user_id
    assert fake_session.committed is False
