import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from api.routes import auth


class _FakeSession:
    def __init__(self, *, users):
        self._users = users
        self.committed = False

    async def get(self, _model, model_id):
        return self._users.get(model_id)

    async def execute(self, _query):
        raise AssertionError("execute should not run when global admin guard rejects the request")

    async def commit(self):
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_update_role_rejects_demotion_of_global_admin(monkeypatch):
    """Demoting a global_admin via the per-org role endpoint must 400.

    The global role overrides the org-level role, so silently flipping the
    org-level membership.role gives the impression of a successful demotion
    while the user retains admin power everywhere — exactly the BAS-571 case.
    """
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    requester_id = UUID("22222222-2222-2222-2222-222222222222")
    target_id = UUID("33333333-3333-3333-3333-333333333333")

    requester = SimpleNamespace(id=requester_id, is_guest=False, role="admin", roles=[])
    target_user = SimpleNamespace(id=target_id, is_guest=False, role=None, roles=["global_admin"])

    fake_session = _FakeSession(users={requester_id: requester, target_id: target_user})
    monkeypatch.setattr(auth, "get_admin_session", lambda: _FakeSessionContext(fake_session))

    async def _allow_admin(*_args, **_kwargs):
        return True

    monkeypatch.setattr(auth, "_can_administer_org", _allow_admin)

    request = auth.UpdateMemberRoleRequest(role="member")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.update_organization_member_role(
                org_id=str(org_id),
                target_user_id=str(target_id),
                request=request,
                user_id=str(requester_id),
            )
        )

    assert exc.value.status_code == 400
    assert "global admin" in exc.value.detail.lower()
    assert not fake_session.committed
