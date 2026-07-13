from __future__ import annotations

import re

from video_agent.contracts import Narration, NarrationBeat


MARKUP_RE = re.compile(r"<#(?:\d+(?:\.\d+)?)#>")


def strip_tts_markup(text: str) -> str:
    return MARKUP_RE.sub("", text)


def compile_beat_markup(beat: NarrationBeat) -> str:
    return beat.spoken_text


def compile_narration_markup(narration: Narration) -> str:
    parts = [compile_beat_markup(beat) for beat in narration.beats]
    if not parts:
        raise ValueError("narration has no beats")
    return "\n".join(parts)
