from agents.orchestrator import SYSTEM_PROMPT_MAIN


def test_system_prompt_allows_intentionally_empty_response() -> None:
    assert "may do nothing and send an intentionally empty response" in SYSTEM_PROMPT_MAIN
