from __future__ import annotations

import re

from video_agent.contracts import Narration, NarrationBeat


_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?])\s+|\n+")
def split_fixed_script(text: str) -> list[str]:
    """Split a locked script into speakable sentences without rewriting it."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("script text must not be empty")
    return [part.strip() for part in _SENTENCE_BREAK.split(normalized) if part.strip()]


def locked_narration_from_text(case_id: str, text: str) -> Narration:
    """Preserve user-authored copy without inferring visual semantics."""

    beats: list[NarrationBeat] = []
    for index, sentence in enumerate(split_fixed_script(text), start=1):
        beats.append(
            NarrationBeat(
                beat_id=f"beat_{index:03d}",
                spoken_text=sentence,
                visual_strategy="auto",
                asset_slots=[],
                hit_phrases=[],
            )
        )
    return Narration(
        case_id=case_id,
        beats=beats,
        voice_style="清晰、自然、有节奏，固定文案口播",
    )
