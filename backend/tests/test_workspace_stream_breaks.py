from messengers._workspace import _find_safe_stream_break


def test_find_safe_stream_break_prefers_sentence_boundary() -> None:
    text = "First sentence. Second sentence"
    assert _find_safe_stream_break(text) == len("First sentence. ")


def test_find_safe_stream_break_skips_apostrophe_s_boundary() -> None:
    text = "The user's. request is queued"
    assert _find_safe_stream_break(text) == 0


def test_find_safe_stream_break_skips_formatting_mark_boundaries() -> None:
    assert _find_safe_stream_break("Wrapped in **. bold") == 0
    assert _find_safe_stream_break("Wrapped in ~. strike") == 0
