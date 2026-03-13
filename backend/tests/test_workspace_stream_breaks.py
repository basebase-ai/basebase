from messengers._stream_breaks import find_safe_break


def test_find_safe_stream_break_best_prefers_farthest_sentence_boundary() -> None:
    text = "First sentence. Second sentence? Third sentence"
    assert find_safe_break(text, strategy="best") == len("First sentence. Second sentence? ")


def test_find_safe_stream_break_quickest_safe_returns_earliest_boundary() -> None:
    text = "First sentence. Second sentence? Third sentence"
    assert find_safe_break(text, strategy="quickest_safe") == len("First sentence. ")


def test_find_safe_stream_break_skips_apostrophe_s_boundary() -> None:
    text = "The user's. request is queued"
    assert find_safe_break(text, strategy="best") == 0


def test_find_safe_stream_break_skips_formatting_mark_boundaries() -> None:
    assert find_safe_break("Wrapped in **. bold", strategy="best") == 0
    assert find_safe_break("Wrapped in ~. strike", strategy="best") == 0
