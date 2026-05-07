from api.routes import chat


def test_derive_bucket_returns_direct_for_private_scope() -> None:
    assert chat._derive_bucket(source="slack", scope="private", normalized_channel_id="C123") == (
        "direct",
        "direct",
    )


def test_derive_bucket_returns_direct_for_web_source() -> None:
    assert chat._derive_bucket(source="web", scope="shared", normalized_channel_id=None) == (
        "direct",
        "direct",
    )


def test_derive_bucket_returns_channel_for_non_dm_slack_channel() -> None:
    assert chat._derive_bucket(source="slack", scope="shared", normalized_channel_id="C123") == (
        "channel",
        "channel:C123",
    )


def test_derive_bucket_returns_direct_for_slack_dm_channel() -> None:
    assert chat._derive_bucket(source="slack", scope="shared", normalized_channel_id="D123") == (
        "direct",
        "direct",
    )


def test_derive_bucket_returns_uncategorized_for_other_sources() -> None:
    assert chat._derive_bucket(source="teams", scope="shared", normalized_channel_id=None) == (
        "uncategorized",
        "uncategorized",
    )


def test_parse_conversation_ids_preserves_order_and_deduplicates_valid_ids() -> None:
    first = "11111111-1111-4111-8111-111111111111"
    second = "22222222-2222-4222-8222-222222222222"

    parsed = chat._parse_conversation_ids(f" {first},not-a-uuid,{second},{first}, ")

    assert [str(value) for value in parsed] == [first, second]


def test_parse_conversation_ids_returns_empty_for_blank_values() -> None:
    assert chat._parse_conversation_ids(None) == []
    assert chat._parse_conversation_ids(" , ") == []
