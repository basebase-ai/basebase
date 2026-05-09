from __future__ import annotations

from pathlib import Path


def test_web_conversation_buckets_are_direct() -> None:
    from api.routes.chat import _derive_bucket

    assert _derive_bucket(source="web", scope="shared", normalized_channel_id=None) == (
        "direct",
        "direct",
    )


def test_frontend_add_conversation_preserves_sidebar_list_and_defaults_direct() -> None:
    store_source = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/store/chatStore.ts"
    ).read_text(encoding="utf-8")

    assert "...recentChats.slice(0, 9)" not in store_source
    assert "...recentChats," in store_source
    assert 'groupBucketType: metadata.groupBucketType ?? "direct"' in store_source
    assert 'groupBucketKey: metadata.groupBucketKey ?? "direct"' in store_source
