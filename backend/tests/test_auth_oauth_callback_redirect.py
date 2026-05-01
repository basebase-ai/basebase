from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_oauth_callback_missing_state_redirects_to_login() -> None:
    response = client.get("/api/auth/oauth/callback", params={"code": "abc"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].endswith("/login?reason=missing_state")


def test_oauth_callback_with_state_redirects_to_nango_and_preserves_query() -> None:
    response = client.get(
        "/api/auth/oauth/callback",
        params={"state": "s1", "code": "abc", "scope": "read"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://api.nango.dev/oauth/callback?")
    assert "state=s1" in location
    assert "code=abc" in location
    assert "scope=read" in location


def test_oauth_callback_no_query_string_redirects_to_login() -> None:
    response = client.get("/api/auth/oauth/callback", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].endswith("/login?reason=missing_state")
