from __future__ import annotations

import re
from typing import Any

_END_PUNCTUATION = set("。！？!?；;\n")
_SOFT_PUNCTUATION = set("，,、：:")


def _frame(ms: int, fps: int) -> int:
    return max(0, round(ms / 1000 * fps))


def build_subtitle_cues(
    tokens: list[dict[str, Any]],
    *,
    fps: int = 30,
    max_chars: int = 14,
    max_duration_ms: int = 2600,
) -> list[dict[str, Any]]:
    """Compile MiniMax word tokens into readable Remotion subtitle cues.

    The displayed text comes from the spoken word tokens and every cue keeps the
    original word-level timing boundary. This preserves the source branch's core
    invariant: voice, subtitle and visual scene anchors share one timing source.
    """
    clean = [
        {
            "text": str(item.get("text") or ""),
            "start_ms": int(item.get("start_ms") or 0),
            "end_ms": int(item.get("end_ms") or 0),
        }
        for item in tokens
        if str(item.get("text") or "").strip() and int(item.get("end_ms") or 0) > int(item.get("start_ms") or 0)
    ]
    cues: list[dict[str, Any]] = []
    group: list[dict[str, Any]] = []

    def flush() -> None:
        if not group:
            return
        text = "".join(part["text"] for part in group).strip()
        if not text:
            group.clear()
            return
        start_ms = group[0]["start_ms"]
        end_ms = group[-1]["end_ms"]
        cues.append(
            {
                "cue_id": f"cue_{len(cues) + 1:03d}",
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "start_frame": _frame(start_ms, fps),
                "end_frame": max(_frame(end_ms, fps), _frame(start_ms, fps) + 1),
            }
        )
        group.clear()

    for token in clean:
        group.append(token)
        text = "".join(part["text"] for part in group)
        duration_ms = group[-1]["end_ms"] - group[0]["start_ms"]
        tail = token["text"][-1]
        should_break = (
            tail in _END_PUNCTUATION
            or len(re.sub(r"\s+", "", text)) >= max_chars
            or duration_ms >= max_duration_ms
            or (tail in _SOFT_PUNCTUATION and len(text) >= max_chars - 3)
        )
        if should_break:
            flush()
    flush()
    return cues


def cue_text(cues: list[dict[str, Any]]) -> str:
    return "".join(str(cue.get("text") or "") for cue in cues)
