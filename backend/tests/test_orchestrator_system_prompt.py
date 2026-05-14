from agents.orchestrator import SYSTEM_PROMPT_MAIN


def test_system_prompt_allows_intentionally_empty_response() -> None:
    assert "may do nothing and send an intentionally empty response" in SYSTEM_PROMPT_MAIN


def test_system_prompt_documents_slack_say_nothing_sentinel() -> None:
    assert "output exactly `SAY_NOTHING`" in SYSTEM_PROMPT_MAIN
    assert "Slack delivery will suppress that token" in SYSTEM_PROMPT_MAIN
