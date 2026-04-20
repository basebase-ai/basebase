import asyncio

from messengers.slack import SlackMessenger


def test_download_file_fetches_metadata_for_embedded_file(monkeypatch) -> None:
    messenger = SlackMessenger()
    captured_file_ids: list[str] = []

    class _FakeConnector:
        async def get_file_info(self, file_id: str):
            captured_file_ids.append(file_id)
            return {
                "id": file_id,
                "name": "embed.pdf",
                "mimetype": "application/pdf",
                "size": 16,
                "url_private_download": "https://files.slack.test/download/F111",
            }

        async def get_oauth_token(self):
            return ("xoxb-test-token", "conn-1")

    class _FakeResponse:
        is_redirect = False
        headers = {"content-type": "application/pdf"}
        content = b"%PDF-1.7 mockdata"

        def raise_for_status(self) -> None:
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            return _FakeResponse()

    async def _fake_get_connector(self, workspace_id=None, organization_id=None):
        return _FakeConnector()

    monkeypatch.setattr(SlackMessenger, "_get_connector", _fake_get_connector)
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)

    async def _run():
        return await messenger.download_file(
            {"external_id": "F111", "source": "slack"},
            workspace_id="T123",
            organization_id="org-1",
        )

    result = asyncio.run(_run())
    assert result is not None
    data, filename, content_type = result
    assert data.startswith(b"%PDF")
    assert filename == "embed.pdf"
    assert content_type == "application/pdf"
    assert captured_file_ids == ["F111"]
