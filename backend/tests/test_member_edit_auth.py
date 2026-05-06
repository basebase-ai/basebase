import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from api.routes import auth


class _FakeSession:
    def __init__(self, *, users):
        self._users = users
        self.executed = False
        self.committed = False

    async def get(self, _model, model_id):
        return self._users.get(model_id)

    async def execute(self, _query):
        self.executed = True
        raise AssertionError(
            "execute should not run when authorization rejects the request"
        )

    async def commit(self):
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _auth_context(user_id: UUID) -> auth.AuthContext:
    return auth.AuthContext(
        user_id=user_id,
        organization_id=UUID("11111111-1111-1111-1111-111111111111"),
        email="member@example.com",
        role="member",
        is_global_admin=False,
    )


def test_member_update_rejects_spoofed_query_user_id_before_self_edit_check(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    authenticated_user_id = UUID("22222222-2222-2222-2222-222222222222")
    spoofed_admin_id = UUID("33333333-3333-3333-3333-333333333333")
    target_user_id = UUID("44444444-4444-4444-4444-444444444444")

    fake_session = _FakeSession(
        users={authenticated_user_id: SimpleNamespace(id=authenticated_user_id)}
    )
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeSessionContext(fake_session)
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.update_organization_member(
                org_id=str(org_id),
                target_user_id=str(target_user_id),
                request=auth.UpdateMemberRequest(title="VP Sales"),
                auth=_auth_context(authenticated_user_id),
                user_id=str(spoofed_admin_id),
            )
        )

    assert exc.value.status_code == 403
    assert "authenticated user" in exc.value.detail
    assert not fake_session.executed
    assert not fake_session.committed


def test_member_update_rejects_non_admin_editing_another_member(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    requester_id = UUID("22222222-2222-2222-2222-222222222222")
    target_user_id = UUID("33333333-3333-3333-3333-333333333333")

    fake_session = _FakeSession(users={requester_id: SimpleNamespace(id=requester_id)})
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeSessionContext(fake_session)
    )

    async def _deny_admin(*_args, **_kwargs):
        return False

    monkeypatch.setattr(auth, "_can_administer_org", _deny_admin)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.update_organization_member(
                org_id=str(org_id),
                target_user_id=str(target_user_id),
                request=auth.UpdateMemberRequest(title="VP Sales"),
                auth=_auth_context(requester_id),
                user_id=str(requester_id),
            )
        )

    assert exc.value.status_code == 403
    assert "own membership" in exc.value.detail
    assert not fake_session.executed
    assert not fake_session.committed


def test_member_remove_rejects_spoofed_query_user_id_before_admin_check(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    authenticated_user_id = UUID("22222222-2222-2222-2222-222222222222")
    spoofed_admin_id = UUID("33333333-3333-3333-3333-333333333333")
    target_user_id = UUID("44444444-4444-4444-4444-444444444444")

    fake_session = _FakeSession(
        users={authenticated_user_id: SimpleNamespace(id=authenticated_user_id)}
    )
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeSessionContext(fake_session)
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.remove_organization_member(
                org_id=str(org_id),
                target_user_id=str(target_user_id),
                auth=_auth_context(authenticated_user_id),
                user_id=str(spoofed_admin_id),
            )
        )

    assert exc.value.status_code == 403
    assert "authenticated user" in exc.value.detail
    assert not fake_session.executed
    assert not fake_session.committed


class _FakeBackgroundTasks:
    def add_task(self, *_args, **_kwargs):
        raise AssertionError(
            "background task should not be queued when authorization rejects"
        )


def test_link_identity_rejects_non_admin_member(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    requester_id = UUID("22222222-2222-2222-2222-222222222222")
    target_user_id = UUID("33333333-3333-3333-3333-333333333333")
    mapping_id = UUID("44444444-4444-4444-4444-444444444444")

    fake_session = _FakeSession(users={requester_id: SimpleNamespace(id=requester_id)})
    monkeypatch.setattr(
        auth, "get_session", lambda **_kwargs: _FakeSessionContext(fake_session)
    )

    async def _deny_admin(*_args, **_kwargs):
        return False

    monkeypatch.setattr(auth, "_can_administer_org", _deny_admin)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.link_identity(
                org_id=str(org_id),
                request=auth.LinkIdentityRequest(
                    target_user_id=str(target_user_id),
                    mapping_id=str(mapping_id),
                ),
                auth=_auth_context(requester_id),
                user_id=str(requester_id),
            )
        )

    assert exc.value.status_code == 403
    assert "admin" in exc.value.detail.lower()
    assert not fake_session.executed
    assert not fake_session.committed


def test_invite_rejects_spoofed_query_user_id_before_admin_check(monkeypatch):
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    authenticated_user_id = UUID("22222222-2222-2222-2222-222222222222")
    spoofed_admin_id = UUID("33333333-3333-3333-3333-333333333333")

    fake_session = _FakeSession(
        users={authenticated_user_id: SimpleNamespace(id=authenticated_user_id)}
    )
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeSessionContext(fake_session)
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.invite_to_organization(
                org_id=str(org_id),
                request=auth.InviteToOrgRequest(
                    email="new-user@example.com", role="member"
                ),
                background_tasks=_FakeBackgroundTasks(),
                auth=_auth_context(authenticated_user_id),
                user_id=str(spoofed_admin_id),
            )
        )

    assert exc.value.status_code == 403
    assert "authenticated user" in exc.value.detail
    assert not fake_session.executed
    assert not fake_session.committed


def test_update_profile_rejects_spoofed_query_user_id_before_user_edit(monkeypatch):
    authenticated_user_id = UUID("22222222-2222-2222-2222-222222222222")
    spoofed_user_id = UUID("33333333-3333-3333-3333-333333333333")

    fake_session = _FakeSession(
        users={authenticated_user_id: SimpleNamespace(id=authenticated_user_id)}
    )
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeSessionContext(fake_session)
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.update_profile(
                request=auth.UpdateProfileRequest(name="Evil Edit"),
                auth=_auth_context(authenticated_user_id),
                user_id=str(spoofed_user_id),
            )
        )

    assert exc.value.status_code == 403
    assert "authenticated user" in exc.value.detail
    assert not fake_session.executed
    assert not fake_session.committed
