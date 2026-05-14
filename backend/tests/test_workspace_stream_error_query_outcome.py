import asyncio

from messengers._workspace import WorkspaceMessenger
from services.llm_adapter import (
    DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE,
    DeepSeekImageUnsupportedError,
)
from messengers.base import InboundMessage, MessageType, MessengerMeta, ResponseMode


class _TestWorkspaceMessenger(WorkspaceMessenger):
    meta = MessengerMeta(
        name="Test",
        slug="test",
        response_mode=ResponseMode.STREAMING,
    )

    def __init__(self) -> None:
        self.posted_messages: list[dict[str, str | None]] = []

    async def resolve_organization(self, user, message):  # type: ignore[override]
        raise NotImplementedError

    async def find_or_create_conversation(self, organization_id, user, message):  # type: ignore[override]
        raise NotImplementedError

    async def download_attachments(self, message):  # type: ignore[override]
        raise NotImplementedError

    def format_text(self, markdown: str) -> str:
        return markdown

    async def post_message(
        self,
        channel_id: str,
        text: str,
        thread_id: str | None = None,
        *,
        workspace_id: str | None = None,
        organization_id: str | None = None,
    ) -> str | None:
        self.posted_messages.append(
            {
                "channel_id": channel_id,
                "text": text,
                "thread_id": thread_id,
                "workspace_id": workspace_id,
                "organization_id": organization_id,
            }
        )
        return "posted"


class _ExplodingOrchestrator:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or RuntimeError("backend stream failed")

    async def process_message(self, *_args, **_kwargs):
        if False:
            yield ""
        raise self.exc


def test_stream_and_post_responses_marks_query_failed_on_fallback_error_copy() -> None:
    messenger = _TestWorkspaceMessenger()
    message = InboundMessage(
        external_user_id="U123",
        text="hello",
        message_type=MessageType.DIRECT,
        messenger_context={"channel_id": "C123", "thread_ts": "t-1", "workspace_id": "W123"},
        message_id="m-1",
    )

    async def _run() -> tuple[int, bool, str | None]:
        return await messenger.stream_and_post_responses(
            orchestrator=_ExplodingOrchestrator(),
            message=message,
            message_text="hello",
            attachment_ids=None,
            organization_id="org-1",
        )

    total, query_failed, failure_reason = asyncio.run(_run())

    assert query_failed is True
    assert failure_reason == "backend stream failed"
    assert total > 0
    assert messenger.posted_messages[-1]["text"] == "Sorry, something went wrong processing your message. Please try again."


def test_stream_and_post_responses_posts_deepseek_image_error_copy() -> None:
    messenger = _TestWorkspaceMessenger()
    message = InboundMessage(
        external_user_id="U123",
        text="hello",
        message_type=MessageType.DIRECT,
        messenger_context={"channel_id": "C123", "thread_ts": "t-1", "workspace_id": "W123"},
        message_id="m-1",
    )

    async def _run() -> tuple[int, bool, str | None]:
        return await messenger.stream_and_post_responses(
            orchestrator=_ExplodingOrchestrator(
                DeepSeekImageUnsupportedError(DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE)
            ),
            message=message,
            message_text="hello",
            attachment_ids=["image-upload-1"],
            organization_id="org-1",
        )

    total, query_failed, failure_reason = asyncio.run(_run())

    assert query_failed is True
    assert failure_reason == DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE
    assert total > 0
    assert messenger.posted_messages[-1]["text"] == DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE


class _SayNothingOrchestrator:
    async def process_message(self, *_args, **_kwargs):
        yield "SAY_NOTHING"


def test_stream_and_post_responses_suppresses_say_nothing_sentinel() -> None:
    messenger = _TestWorkspaceMessenger()
    message = InboundMessage(
        external_user_id="U123",
        text="thanks",
        message_type=MessageType.DIRECT,
        messenger_context={"channel_id": "C123", "thread_ts": "t-1", "workspace_id": "W123"},
        message_id="m-1",
    )

    async def _run() -> tuple[int, bool, str | None]:
        return await messenger.stream_and_post_responses(
            orchestrator=_SayNothingOrchestrator(),
            message=message,
            message_text="thanks",
            attachment_ids=None,
            organization_id="org-1",
        )

    total, query_failed, failure_reason = asyncio.run(_run())

    assert total == 0
    assert query_failed is False
    assert failure_reason is None
    assert messenger.posted_messages == []
