from api.routes.apps import _strip_screenshot


def test_strip_screenshot_keeps_snapshot_metadata_without_payload() -> None:
    config = {
        "screenshot": "data:image/jpeg;base64,abc",
        "screenshot_captured_at": "2026-05-08T12:00:00Z",
        "preferred_mode": "mini_app",
    }

    stripped = _strip_screenshot(config)

    assert stripped == {
        "has_screenshot": True,
        "screenshot_captured_at": "2026-05-08T12:00:00Z",
        "preferred_mode": "mini_app",
    }
    assert "screenshot" not in stripped
    assert config["screenshot"] == "data:image/jpeg;base64,abc"


def test_strip_screenshot_leaves_configs_without_snapshot_unchanged() -> None:
    config = {"preferred_mode": "icon"}

    assert _strip_screenshot(config) is config
