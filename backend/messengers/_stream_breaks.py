from __future__ import annotations

import re
from typing import Literal

StreamBreakStrategy = Literal["best", "quickest_safe"]

_SENTENCE_BREAK_RE: re.Pattern[str] = re.compile(r"[.!?](?:\s|$)")


def _is_valid_sentence_break(text: str, punct_idx: int) -> bool:
    """Return whether punctuation index is safe to break on."""
    if punct_idx >= 2 and text[punct_idx - 2:punct_idx] in {"'s", "'S"}:
        return False
    if punct_idx >= 2 and text[punct_idx - 2:punct_idx] == "**":
        return False
    if punct_idx >= 1 and text[punct_idx - 1:punct_idx] == "~":
        return False
    return True


def find_safe_break(
    text: str,
    *,
    strategy: StreamBreakStrategy = "best",
    limit: int | None = None,
) -> int:
    """Find a safe break index for streamed/segmented text.

    - ``best``: choose the farthest safe sentence break within ``limit``.
    - ``quickest_safe``: choose the first safe sentence break within ``limit``.
    """
    if not text:
        return 0

    max_index: int = len(text) if limit is None else min(limit, len(text))
    if max_index <= 0:
        return 0

    selected_break: int = 0
    for match in _SENTENCE_BREAK_RE.finditer(text):
        candidate: int = match.end()
        if candidate > max_index:
            break
        punct_idx: int = match.start()
        if not _is_valid_sentence_break(text, punct_idx):
            continue
        if strategy == "quickest_safe":
            return candidate
        selected_break = candidate

    if selected_break > 0:
        return selected_break

    # For unbounded streaming buffers, only sentence-safe boundaries are used.
    if limit is None:
        return 0

    # Fallback when no sentence boundary is available in the bounded window.
    newline_break: int = text.rfind("\n", 0, max_index)
    if newline_break > 0:
        return newline_break

    space_break: int = text.rfind(" ", 0, max_index)
    if space_break > 0:
        return space_break

    return max_index if max_index < len(text) else 0

