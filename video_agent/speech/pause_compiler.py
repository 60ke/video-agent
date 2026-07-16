from __future__ import annotations

import re

from video_agent.contracts import Narration, NarrationBeat


MARKUP_RE = re.compile(r"<#(?:\d+(?:\.\d+)?)#>")


def strip_tts_markup(text: str) -> str:
    return MARKUP_RE.sub("", text)


def compile_beat_markup(beat: NarrationBeat) -> str:
    text = beat.spoken_text
    if not beat.pause_intents:
        return text

    # Apply intents from the end so each phrase location remains stable. The
    # MiniMax tag must sit between pronounceable text, hence a pause after a
    # final phrase is deliberately ignored instead of producing invalid markup.
    placements: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for intent in beat.pause_intents:
        if intent.after_phrase in seen:
            raise ValueError(f"duplicate pause intent after phrase: {intent.after_phrase}")
        seen.add(intent.after_phrase)
        index = text.find(intent.after_phrase)
        if index < 0:
            raise ValueError(f"pause phrase is not present in spoken_text: {intent.after_phrase}")
        end = index + len(intent.after_phrase)
        if not text[end:].strip():
            continue
        seconds = intent.requested_ms / 1000
        tag = f"<#{seconds:.2f}#>"
        placements.append((index, end, tag))

    for _start, end, tag in sorted(placements, key=lambda value: value[1], reverse=True):
        text = f"{text[:end]}{tag}{text[end:]}"
    return text


def compile_narration_markup(narration: Narration) -> str:
    parts = [compile_beat_markup(beat) for beat in narration.beats]
    if not parts:
        raise ValueError("narration has no beats")
    return "\n".join(parts)
