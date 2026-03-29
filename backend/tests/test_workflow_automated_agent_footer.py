from workers.tasks import workflows


def test_workflow_footer_appends_once() -> None:
    signed = workflows._ensure_automated_agent_footer("Hello from workflow")
    assert "Done by an automated agent" in signed
    assert signed.endswith("Done by an automated agent via Basebase.")

    signed_again = workflows._ensure_automated_agent_footer(signed)
    assert signed_again == signed


def test_workflow_footer_handles_empty_body() -> None:
    signed = workflows._ensure_automated_agent_footer("")
    assert signed == "— Done by an automated agent via Basebase."
