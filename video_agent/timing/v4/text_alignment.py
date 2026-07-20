"""Text alignment helpers for V4 Anchor Compiler."""

from __future__ import annotations

from video_agent.timing.v4.speech_lock import normalize_text


def compact_chars(text: str) -> str:
    return normalize_text(text)


def project_char_span_to_token_ids(
    *,
    tokens: list[tuple[str, str]],
    start_char: int,
    end_char: int,
) -> list[str]:
    """Map a normalized character span onto intersecting token ids.

    tokens: list of (token_id, normalized_text)
    """
    cursor = 0
    hit: list[str] = []
    for token_id, text in tokens:
        token_start = cursor
        token_end = cursor + len(text)
        cursor = token_end
        if token_end <= start_char:
            continue
        if token_start >= end_char:
            break
        hit.append(token_id)
    return hit
