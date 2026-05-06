import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from api.auth_middleware import AuthContext
from api.routes import auth


ORG_ID = UUID("11111111-1111-1111-1111-111111111111")
REQUESTER_ID = UUID("22222222-2222-2222-2222-222222222222")
TARGET_ID = UUID("33333333-3333-3333-3333-333333333333")
SOURCE_ID = UUID("44444444-4444-4444-4444-444444444444")


def _auth_context(*, is_global_admin: bool) -> AuthContext:
    return AuthContext(
        user_id=REQUESTER_ID,
        organization_id=ORG_ID,
        email="admin@example.com",
        role="global_admin" if is_global_admin else "admin",
        is_global_admin=is_global_admin,
    )


def _merge_request() -> auth.MergeUsersRequest:
    return auth.MergeUsersRequest(
        target_user_id=str(TARGET_ID),
        source_user_id=str(SOURCE_ID),
        delete_source=True,
    )


def test_merge_users_endpoint_rejects_org_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Org admins cannot merge users; the operation is global-admin only."""

    async def _unexpected_merge(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("merge_users should not run for non-global admins")

    import services.user_merge as user_merge

    monkeypatch.setattr(user_merge, "merge_users", _unexpected_merge)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            auth.merge_users_endpoint(
                request=_merge_request(),
                auth=_auth_context(is_global_admin=False),
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "Global admin access required"


def test_merge_users_endpoint_allows_global_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Global admins can initiate user merges."""

    calls: list[dict[str, object]] = []

    async def _fake_merge_users(**kwargs: object) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            target_user_id=kwargs["target_user_id"],
            source_user_id=kwargs["source_user_id"],
            source_email="source@example.com",
            tables_updated={"users (deleted)": 1},
            error=None,
        )

    import services.user_merge as user_merge

    monkeypatch.setattr(user_merge, "merge_users", _fake_merge_users)

    response = asyncio.run(
        auth.merge_users_endpoint(
            request=_merge_request(),
            auth=_auth_context(is_global_admin=True),
        )
    )

    assert response.success is True
    assert response.target_user_id == str(TARGET_ID)
    assert response.source_user_id == str(SOURCE_ID)
    assert response.source_email == "source@example.com"
    assert response.tables_updated == {"users (deleted)": 1}
    assert calls == [
        {
            "target_user_id": str(TARGET_ID),
            "source_user_id": str(SOURCE_ID),
            "organization_id": str(ORG_ID),
            "delete_source": True,
        }
    ]
