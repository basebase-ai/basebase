from messengers._twilio_phone import _split_text


def test_twilio_split_text_uses_best_safe_breaks() -> None:
    text = "One short sentence. Two short sentence. Three"
    segments = _split_text(text, max_len=len("One short sentence. Two short sentence. T"))
    assert segments == ["One short sentence. Two short sentence.", "Three"]
