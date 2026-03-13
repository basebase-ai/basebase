from messengers._text_breaks import find_safe_text_break
from messengers._twilio_phone import _split_text
from messengers._workspace import _find_safe_stream_break


def test_workspace_uses_quickest_safe_sentence_break() -> None:
    text = "First sentence. Second sentence."
    assert _find_safe_stream_break(text) == len("First sentence. ")


def test_safe_break_skips_disallowed_boundaries() -> None:
    assert find_safe_text_break("The user's. request", preference="quickest_safe") == 0
    assert find_safe_text_break("Wrapped in **. bold", preference="quickest_safe") == 0
    assert find_safe_text_break("Wrapped in ~. strike", preference="quickest_safe") == 0


def test_twilio_split_prefers_best_sentence_break_within_limit() -> None:
    text = "First short sentence. Second sentence is long enough to split here"
    segments = _split_text(text, max_len=35)
    assert segments[0] == "First short sentence."
    assert "Second sentence" in segments[1]


def test_twilio_split_falls_back_to_whitespace_when_no_sentence_boundary() -> None:
    text = "word " * 20
    segments = _split_text(text.strip(), max_len=20)
    assert all(len(segment) <= 20 for segment in segments)
