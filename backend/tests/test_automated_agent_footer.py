from services.automated_agent_footer import AUTOMATED_AGENT_FOOTER, ensure_automated_agent_footer


def test_ensure_automated_agent_footer_adds_footer_once() -> None:
    signed = ensure_automated_agent_footer("Hello there")
    assert AUTOMATED_AGENT_FOOTER in signed
    assert signed.startswith("Hello there")

    signed_again = ensure_automated_agent_footer(signed)
    assert signed_again == signed


def test_ensure_automated_agent_footer_handles_empty_text() -> None:
    signed = ensure_automated_agent_footer("")
    assert signed == f"— {AUTOMATED_AGENT_FOOTER}"
