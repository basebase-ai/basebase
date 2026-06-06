from __future__ import annotations

import asyncio

from services import egress_scanner


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed: bool = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def test_estimate_bytes_out_counts_utf8_payload() -> None:
    payload = {"message": "héllo", "count": 3}
    byte_count = egress_scanner.estimate_bytes_out(payload)
    assert byte_count > len("héllo")
    assert isinstance(byte_count, int)


def test_record_count_only_egress_event_writes_append_only_row(monkeypatch) -> None:
    fake_session = _FakeSession()

    def _fake_get_session(_org_id: str) -> _FakeSessionCtx:
        return _FakeSessionCtx(fake_session)

    monkeypatch.setattr(egress_scanner, "get_session", _fake_get_session)

    asyncio.run(
        egress_scanner.record_count_only_egress_event(
            organization_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
            context={"conversation_id": "33333333-3333-3333-3333-333333333333"},
            connector="code_sandbox",
            operation="execute_command",
            payload={"command": "echo hello"},
            destination="sandbox",
            metadata={"dispatch_type": "action"},
        )
    )

    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    row = fake_session.added[0]
    assert row.connector == "code_sandbox"
    assert row.operation == "execute_command"
    assert row.bytes_out > 0
    assert row.scan_mode == "count_only"
