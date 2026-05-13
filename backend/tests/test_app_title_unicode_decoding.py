import asyncio
from contextlib import asynccontextmanager

from connectors.apps import AppsConnector
from utils.text_encoding import decode_escaped_unicode_text


class _FakeExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _CreateSession:
    def __init__(self):
        self.added = []
        self.committed = False

    async def execute(self, query, _params=None):
        if "organizations.handle" in str(query):
            return _FakeExecuteResult(None)
        raise AssertionError(f"Unexpected query: {query}")

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def test_decode_escaped_unicode_text_decodes_surrogate_pair_escape():
    assert decode_escaped_unicode_text(r"Chat \uD83D\uDCAC") == "Chat 💬"


def test_decode_escaped_unicode_text_decodes_bmp_escape_without_touching_plain_emoji():
    assert decode_escaped_unicode_text(r"Caf\u00E9 💬") == "Café 💬"


def test_apps_connector_create_normalizes_escaped_unicode_title(monkeypatch):
    fake_session = _CreateSession()

    @asynccontextmanager
    async def _fake_get_session(*_args, **_kwargs):
        yield fake_session

    async def _fake_warm(*_args, **_kwargs):
        return None

    async def _fake_test_execute_queries(*_args, **_kwargs):
        return []

    monkeypatch.setattr("connectors.apps.get_session", _fake_get_session)
    monkeypatch.setattr("connectors.apps.warm_public_preview_cache", _fake_warm)
    monkeypatch.setattr("utils.transpile_jsx.transpile_jsx", lambda _code: (None,))
    monkeypatch.setattr(
        "connectors.apps.AppsConnector._test_execute_queries",
        _fake_test_execute_queries,
    )

    connector = AppsConnector(
        organization_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )

    result = asyncio.run(
        connector._create(
            {
                "title": r"Chat \uD83D\uDCAC",
                "queries": {"q": {"sql": "SELECT 1 AS n", "params": {}}},
                "frontend_code": "export default function App(){ return <div/>; }",
            }
        )
    )

    assert result["status"] == "success"
    assert result["app"]["title"] == "Chat 💬"
    assert fake_session.added[0].title == "Chat 💬"
    assert fake_session.committed is True
