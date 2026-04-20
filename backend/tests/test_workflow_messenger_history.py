from workers.tasks.workflows import _extract_messenger_connector_call_details


def test_extract_messenger_history_details_for_slack_send_message() -> None:
    details = _extract_messenger_connector_call_details(
        {
            "type": "tool_call",
            "tool_name": "run_on_connector",
            "tool_id": "tool_123",
            "tool_input": {
                "connector": "slack",
                "action": "send_message",
                "params": {
                    "channel": "#ops-alerts",
                    "text": "Deploy finished successfully",
                },
            },
        }
    )

    assert details is not None
    assert details["connector"] == "slack"
    assert details["action"] == "send_message"
    assert details["channel"] == "#ops-alerts"
    assert details["message_preview"] == "Deploy finished successfully"


def test_extract_messenger_history_details_for_twilio_whatsapp() -> None:
    details = _extract_messenger_connector_call_details(
        {
            "tool_name": "run_on_connector",
            "tool_input": {
                "connector": "twilio",
                "action": "send_whatsapp",
                "params": {
                    "to": "+14155550199",
                    "body": "Hello from workflow",
                },
            },
        }
    )

    assert details is not None
    assert details["connector"] == "twilio"
    assert details["action"] == "send_whatsapp"
    assert details["recipient"] == "+14155550199"
    assert details["message_preview"] == "Hello from workflow"


def test_extract_messenger_history_details_ignores_non_messenger_connector() -> None:
    details = _extract_messenger_connector_call_details(
        {
            "tool_name": "run_on_connector",
            "tool_input": {
                "connector": "github",
                "action": "create_issue",
                "params": {"title": "Bug"},
            },
        }
    )
    assert details is None
