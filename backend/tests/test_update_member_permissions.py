import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from api.routes import auth


def _auth_ctx(user_id: UUID, org_id: UUID, *, role: str = "member") -> auth.AuthContext:
    return auth.AuthContext(
        user_id=user_id,
        organization_id=org_id,
        email="requester@example.com",
        role=role,
        is_global_admin=False,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, *, users=None, execute_results=None):
        self._users = users or {}
        self._execute_results = list(execute_results or [])
        self.committed = False

    async def get(self, _model, model_id):
        return self._users.get(model_id)

    async def execute(self, _query):
        if not self._execute_results:
            raise AssertionError("unexpected execute call")
        return self._execute_results.pop(0)

    async def commit(self):
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_update_member_rejects_spoofed_user_id_query_param():
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    requester_id = UUID("22222222-2222-2222-2222-222222222222")
    spoofed_admin_id = UUID("33333333-3333-3333-3333-333333333333")
    target_id = UUID("44444444-4444-4444-4444-444444444444")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.update_organization_member(
                org_id=str(org_id),
                target_user_id=str(target_id),
                request=auth.UpdateMemberRequest(title="VP Sales"),
                auth=_auth_ctx(requester_id, org_id),
                user_id=str(spoofed_admin_id),
            )
        )

    assert exc.value.status_code == 403
    assert "authenticated user" in exc.value.detail


def test_update_member_rejects_non_admin_editing_another_member(monkeypatch):
    org_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    requester_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    target_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    requester = SimpleNamespace(id=requester_id, role="member", roles=[])
    fake_session = _FakeSession(users={requester_id: requester})
    monkeypatch.setattr(auth, "get_admin_session", lambda: _FakeSessionContext(fake_session))

    async def _deny_admin(*_args, **_kwargs):
        return False

    monkeypatch.setattr(auth, "_can_administer_org", _deny_admin)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.update_organization_member(
                org_id=str(org_id),
                target_user_id=str(target_id),
                request=auth.UpdateMemberRequest(title="VP Sales"),
                auth=_auth_ctx(requester_id, org_id),
            )
        )

    assert exc.value.status_code == 403
    assert not fake_session.committed


def test_update_member_allows_org_admin_editing_another_member(monkeypatch):
    org_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    requester_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    target_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    requester = SimpleNamespace(id=requester_id, role="admin", roles=[])
    target_membership = SimpleNamespace(
        id=UUID("12121212-1212-1212-1212-121212121212"),
        user_id=target_id,
        organization_id=org_id,
        status="active",
        title=None,
        reports_to_membership_id=None,
    )
    fake_session = _FakeSession(
        users={requester_id: requester},
        execute_results=[_ScalarResult(target_membership)],
    )
    monkeypatch.setattr(auth, "get_admin_session", lambda: _FakeSessionContext(fake_session))

    async def _allow_admin(*_args, **_kwargs):
        return True

    monkeypatch.setattr(auth, "_can_administer_org", _allow_admin)

    result = asyncio.run(
        auth.update_organization_member(
            org_id=str(org_id),
            target_user_id=str(target_id),
            request=auth.UpdateMemberRequest(title="  VP Sales  "),
            auth=_auth_ctx(requester_id, org_id, role="admin"),
        )
    )

    assert result["status"] == "updated"
    assert result["title"] == "VP Sales"
    assert target_membership.title == "VP Sales"
    assert fake_session.committed
