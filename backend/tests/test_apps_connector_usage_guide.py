from connectors.apps import USAGE_GUIDE


def test_usage_guide_requires_sdk_trigger_workflow_helper() -> None:
    assert "Always call the SDK helper: `triggerWorkflow(...)`" in USAGE_GUIDE
    assert "Do NOT hand-roll `window.parent.postMessage(...)`" in USAGE_GUIDE
    assert "app-trigger-workflow" in USAGE_GUIDE
