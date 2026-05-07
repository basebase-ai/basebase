"""Regression tests for ``POST /auth/users/sync`` ID-migration handling.

Invited / waitlist users have a `users.id` auto-generated before they ever
sign in via Supabase OAuth. When they later sign in, their JWT `sub`
differs from `users.id`. The sync endpoint is supposed to migrate
`users.id` to match the Supabase `sub`, but historically a 403 guard
fired before the migration code ran, leaving the user permanently stuck
("invited" status, can't connect integrations, can't bootstrap).

These tests pin the desired behaviour: validation trusts the
JWT-verified email — not the (potentially mismatched) DB primary key —
so the migration path can run.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException

from api.routes import auth


_DB_ID = UUID("ee3c1568-3df0-4a4c-b0bb-a29d79aa6bc9")
_SUPABASE_SUB = UUID("5ee8316b-ca2d-41c9-be55-b0b355bd71ce")


class _StopValidation(Exception):
    """Sentinel raised inside the fake admin session.

    If the test reaches the admin-session block it means validation has
    accepted the request. We don't want to model the full DB
    interaction, so we raise to short-circuit the rest of the endpoint.
    """


class _FakeAdminSession:
    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise _StopValidation


class _FakeAdminSessionContext:
    async def __aenter__(self) -> _FakeAdminSession:
        return _FakeAdminSession()

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


def _auth_ctx(user_id: UUID, email: str) -> auth.AuthContext:
    return auth.AuthContext(
        user_id=user_id,
        organization_id=None,
        email=email,
        role="member",
        is_global_admin=False,
    )


def _request(user_id: UUID, email: str) -> auth.SyncUserRequest:
    return auth.SyncUserRequest(id=str(user_id), email=email)


def _run_sync(
    *,
    monkeypatch: pytest.MonkeyPatch,
    auth_user_id: UUID,
    auth_email: str,
    request_id: UUID,
    request_email: str,
) -> None:
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeAdminSessionContext()
    )
    asyncio.run(
        auth.sync_user(
            request=_request(request_id, request_email),
            auth=_auth_ctx(auth_user_id, auth_email),
        )
    )


def test_sync_user_accepts_id_mismatch_when_email_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invited-user ID-migration path must not be blocked.

    Reproduces the production deadlock: an invited user's `auth.user_id`
    (resolved by email-fallback in auth_middleware) is the legacy
    auto-generated DB id, while `request.id` is their Supabase `sub`.
    The fix lets validation pass when emails match so the migration
    UPDATE can run.
    """
    with pytest.raises(_StopValidation):
        _run_sync(
            monkeypatch=monkeypatch,
            auth_user_id=_DB_ID,
            auth_email="jim@example.com",
            request_id=_SUPABASE_SUB,
            request_email="jim@example.com",
        )


def test_sync_user_accepts_id_mismatch_when_email_case_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Email comparison must be case-insensitive (matches production behaviour)."""
    with pytest.raises(_StopValidation):
        _run_sync(
            monkeypatch=monkeypatch,
            auth_user_id=_DB_ID,
            auth_email="Jim@Example.com",
            request_id=_SUPABASE_SUB,
            request_email="jim@example.com",
        )


def test_sync_user_rejects_when_emails_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _run_sync(
            monkeypatch=monkeypatch,
            auth_user_id=_DB_ID,
            auth_email="other@example.com",
            request_id=_SUPABASE_SUB,
            request_email="jim@example.com",
        )
    assert exc_info.value.status_code == 403
    assert "Email" in exc_info.value.detail


def test_sync_user_rejects_when_auth_context_has_no_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty auth.email must not silently bypass validation."""
    with pytest.raises(HTTPException) as exc_info:
        _run_sync(
            monkeypatch=monkeypatch,
            auth_user_id=_DB_ID,
            auth_email="",
            request_id=_SUPABASE_SUB,
            request_email="jim@example.com",
        )
    assert exc_info.value.status_code == 403


def test_sync_user_rejects_invalid_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth, "get_admin_session", lambda: _FakeAdminSessionContext()
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth.sync_user(
                request=auth.SyncUserRequest(id="not-a-uuid", email="jim@example.com"),
                auth=_auth_ctx(_DB_ID, "jim@example.com"),
            )
        )
    assert exc_info.value.status_code == 400
