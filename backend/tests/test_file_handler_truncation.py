import io
import sys
import types
import zipfile

from services.file_handler import StoredFile, _pptx_to_text_block, _pptx_slide_sort_key, pdf_to_text_block


def test_pdf_to_text_block_truncates_to_first_250k_chars(monkeypatch):
    class _FakePage:
        def __init__(self, text: str):
            self._text = text

        def get_text(self) -> str:
            return self._text

    class _FakeDoc:
        def __init__(self, text: str):
            self._text = text

        def __len__(self) -> int:
            return 1

        def __getitem__(self, _idx: int):
            return _FakePage(self._text)

        def close(self) -> None:
            return None

    long_text = "A" * 260_000

    fake_module = types.SimpleNamespace(open=lambda *_args, **_kwargs: _FakeDoc(long_text))
    monkeypatch.setitem(sys.modules, "pymupdf", fake_module)

    sf = StoredFile("1", "deck.pdf", "application/pdf", 10, b"x")
    block = pdf_to_text_block(sf)
    text = block["text"]

    assert "showing first 250,000 characters" in text
    marker = "--- Page 1 ---\n"
    preserved = text.split(marker, 1)[1].split("\n\n[Truncated", 1)[0]
    assert len(preserved) == 250_000 - len(marker)
    assert preserved.startswith("A" * 1000)


def test_pptx_to_text_block_uses_numeric_slide_order_and_250k_truncation():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", "<s1>")
        zf.writestr("ppt/slides/slide10.xml", "<s10>")
        zf.writestr("ppt/slides/slide2.xml", "<s2>" + ("Z" * 260_000))

    sf = StoredFile("2", "deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", len(payload.getvalue()), payload.getvalue())
    block = _pptx_to_text_block(sf)
    text = block["text"]

    assert text.index("<s1>") < text.index("<s2>")
    assert "showing first 250,000 characters" in text


def test_pptx_slide_sort_key_is_numeric():
    names = ["ppt/slides/slide10.xml", "ppt/slides/slide2.xml", "ppt/slides/slide1.xml"]
    assert sorted(names, key=_pptx_slide_sort_key) == [
        "ppt/slides/slide1.xml",
        "ppt/slides/slide2.xml",
        "ppt/slides/slide10.xml",
    ]
