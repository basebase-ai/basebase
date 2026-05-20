from config import get_normalized_redis_url


def test_get_normalized_redis_url_keeps_supported_scheme() -> None:
    assert get_normalized_redis_url("rediss://example.com:6379/0") == "rediss://example.com:6379/0"


def test_get_normalized_redis_url_adds_scheme_for_host_port() -> None:
    assert get_normalized_redis_url("example.com:6379") == "redis://example.com:6379"
