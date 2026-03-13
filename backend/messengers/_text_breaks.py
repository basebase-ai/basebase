"""Shared helpers for safely breaking streamed and segmented text."""
from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

BreakPreference = Literal["best", "quickest_safe"]

_SENTENCE_BREAK_RE: re.Pattern[str] = re.compile(r"[.!?](?:\s|$)")


def _is_disallowed_punctuation_break(text: str, punct_idx: int) -> bool:
    """Return True when punctuation at ``punct_idx`` should not be used as a break."""
    if punct_idx >= 2 and text[punct_idx - 2:punct_idx] in {"'s", "'S"}:
        return True
    if punct_idx >= 2 and text[punct_idx - 2:punct_idx] == "**":
        return True
    if punct_idx >= 1 and text[punct_idx - 1:punct_idx] == "~":
        return True
    return False


def find_safe_text_break(
    text: str,
    *,
    preference: BreakPreference,
    max_index: int | None = None,
) -> int:
    """Find a safe index for splitting text.

    - ``quickest_safe`` returns the earliest safe sentence boundary.
    - ``best`` returns the latest safe boundary up to ``max_index``.
    """
    if not text:
        return 0

    limit: int = min(max_index, len(text)) if max_index is not None else len(text)
    if limit <= 0:
        return 0

    sentence_candidates: list[int] = []
    for match in _SENTENCE_BREAK_RE.finditer(text[:limit]):
        punct_idx: int = match.start()
        if _is_disallowed_punctuation_break(text, punct_idx):
            continue
        sentence_candidates.append(match.end())

    if sentence_candidates:
        return sentence_candidates[0] if preference == "quickest_safe" else sentence_candidates[-1]

    # Fallbacks for bounded chunking use-cases (e.g., SMS segmentation).
    if max_index is not None:
        for char in ("\n", " "):
            cut: int = text.rfind(char, 0, limit)
            if cut > 0:
                return cut
        if len(text) > limit:
            return limit

    return 0
