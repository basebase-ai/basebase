"""Utilities for normalizing text received from LLM/tool JSON payloads."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_UNICODE_ESCAPE_RE = re.compile(r"(?:\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8})+")


def _combine_surrogate_code_units(value: str) -> str:
    """Combine UTF-16 surrogate code units in a Python string when possible."""
    if not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
        return value
    try:
        return value.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeDecodeError:
        logger.debug("Unable to combine surrogate code units in text value", exc_info=True)
        return value


def decode_escaped_unicode_text(value: str | None) -> str | None:
    """Decode literal JSON-style Unicode escapes in user-visible text.

    LLM/tool calls can occasionally double-escape titles, storing text such as
    ``"Chat \\uD83D\\uDCAC"`` instead of ``"Chat 💬"``. This helper decodes only
    JSON Unicode escape sequences and also combines valid UTF-16 surrogate pairs
    that Python may retain after JSON parsing.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        chars: list[str] = []
        index = 0
        while index < len(raw):
            escape_type = raw[index + 1]
            width = 8 if escape_type == "U" else 4
            start = index + 2
            end = start + width
            chars.append(chr(int(raw[start:end], 16)))
            index = end
        return _combine_surrogate_code_units("".join(chars))

    decoded = _UNICODE_ESCAPE_RE.sub(_replace, value)
    return _combine_surrogate_code_units(decoded)
