from __future__ import annotations

import re

from video_agent.contracts import Narration, NarrationBeat


PAUSE_SECONDS = {"micro": 0.10, "short": 0.16, "beat": 0.26, "section": 0.38}
MARKUP_RE = re.compile(r"<#(?:\d+(?:\.\d+)?)#>")


def strip_tts_markup(text: str) -> str:
    return MARKUP_RE.sub("", text)


def _insert_pause(text: str, phrase: str, seconds: float) -> str:
    marker = f"<#{seconds:.2f}#>"
    index = text.find(phrase)
    if index < 0:
        raise ValueError(f"pause phrase not found in beat text: {phrase}")
    end = index + len(phrase)
    if text[end : end + 2] == "<#":
        return text
    return text[:end] + marker + text[end:]


def compile_beat_markup(beat: NarrationBeat) -> str:
    if beat.tts_markup_text:
        if strip_tts_markup(beat.tts_markup_text) != beat.spoken_text:
            raise ValueError(f"{beat.beat_id} tts markup changes spoken text")
        return beat.tts_markup_text
    markup = beat.spoken_text
    offset_adjusted: list[tuple[int, str, float]] = []
    for pause in beat.pause_intents:
        index = beat.spoken_text.find(pause.after_phrase)
        if index < 0:
            raise ValueError(f"{beat.beat_id} pause phrase not found: {pause.after_phrase}")
        offset_adjusted.append((index + len(pause.after_phrase), pause.after_phrase, pause.requested_ms / 1000.0))
    for _, phrase, seconds in sorted(offset_adjusted, reverse=True):
        markup = _insert_pause(markup, phrase, seconds)
    return markup


def compile_narration_markup(narration: Narration) -> str:
    parts = [compile_beat_markup(beat) for beat in narration.beats]
    if not parts:
        raise ValueError("narration has no beats")
    return "".join(parts)
