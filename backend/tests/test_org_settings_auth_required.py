from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from api.auth_middleware import AuthContext, get_current_auth
from api.main import app
from api.routes import auth

client = TestClient(app)


def test_update_organization_rejects_unauthenticated_user_id_query() -> None:
    """A guessed admin UUID in query params must not authenticate org updates."""
    org_id = uuid4()
    guessed_admin_id = uuid4()

    response = client.patch(
        f"/api/auth/organizations/{org_id}",
        params={"user_id": str(guessed_admin_id)},
        json={"name": "attacker controlled"},
    )

    assert response.status_code == 401


def test_update_organization_uses_verified_auth_context(monkeypatch) -> None:
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    auth_user_id = UUID("22222222-2222-2222-2222-222222222222")
    attacker_query_user_id = UUID("33333333-3333-3333-3333-333333333333")

    app.dependency_overrides[get_current_auth] = lambda: AuthContext(
        user_id=auth_user_id,
        organization_id=org_id,
        email="admin@example.com",
        role="user",
        is_global_admin=False,
    )

    captured_session_context: dict[str, str | None] = {}
    captured_admin_user_ids: list[UUID] = []

    org = SimpleNamespace(
        id=org_id,
        name="Before",
        email_domain="example.com",
        logo_url=None,
        company_summary=None,
        llm_provider=None,
        llm_primary_model=None,
        llm_cheap_model=None,
        llm_workflow_model=None,
    )
    auth_user = SimpleNamespace(id=auth_user_id, role="user", roles=[])

    class FakeSession:
        async def get(self, model, model_id):
            if model is auth.User:
                captured_admin_user_ids.append(model_id)
                return auth_user if model_id == auth_user_id else None
            if model is auth.Organization and model_id == org_id:
                return org
            return None

        async def commit(self):
            return None

        async def refresh(self, _obj):
            return None

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_get_session(*, organization_id=None, user_id=None):
        captured_session_context["organization_id"] = organization_id
        captured_session_context["user_id"] = user_id
        return FakeSessionContext()

    async def allow_admin(_session, user, checked_org_id):
        assert user is auth_user
        assert checked_org_id == org_id
        return True

    monkeypatch.setattr(auth, "get_session", fake_get_session)
    monkeypatch.setattr(auth, "_can_administer_org", allow_admin)

    try:
        response = client.patch(
            f"/api/auth/organizations/{org_id}",
            params={"user_id": str(attacker_query_user_id)},
            json={"name": "After"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["name"] == "After"
    assert captured_session_context == {
        "organization_id": str(org_id),
        "user_id": str(auth_user_id),
    }
    assert captured_admin_user_ids == [auth_user_id]
    assert org.name == "After"


def test_remove_organization_member_rejects_unauthenticated_user_id_query() -> None:
    org_id = uuid4()
    target_user_id = uuid4()
    guessed_admin_id = uuid4()

    response = client.delete(
        f"/api/auth/organizations/{org_id}/members/{target_user_id}",
        params={"user_id": str(guessed_admin_id)},
    )

    assert response.status_code == 401


def test_update_organization_member_rejects_unauthenticated_user_id_query() -> None:
    org_id = uuid4()
    target_user_id = uuid4()
    guessed_admin_id = uuid4()

    response = client.patch(
        f"/api/auth/organizations/{org_id}/members/{target_user_id}",
        params={"user_id": str(guessed_admin_id)},
        json={"title": "CEO"},
    )

    assert response.status_code == 401
