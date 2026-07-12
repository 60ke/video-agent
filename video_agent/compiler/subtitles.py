from __future__ import annotations

import unicodedata

from video_agent.contracts import PhraseAnchor, SubtitleCue, TimingLock, TokenTiming


BREAK_PUNCTUATION = set("，。！？；：")


def fullwidth_units(text: str) -> float:
    units = 0.0
    for char in text:
        if char.isspace():
            continue
        width = unicodedata.east_asian_width(char)
        units += 1.0 if width in {"W", "F", "A"} else 0.5
    return units


def _emphasis(tokens: list[TokenTiming], anchors: list[PhraseAnchor]) -> str | None:
    ids = {token.token_id for token in tokens}
    matches = [anchor.text for anchor in anchors if ids.intersection(anchor.token_ids)]
    return matches[0] if matches else None


def compile_subtitles(timing: TimingLock, default_slot: str = "subtitle_top", hard_units: float = 10.0) -> list[SubtitleCue]:
    by_beat: dict[str | None, list[TokenTiming]] = {}
    for token in timing.tokens:
        by_beat.setdefault(token.beat_id, []).append(token)

    segments: list[list[TokenTiming]] = []
    for beat_tokens in by_beat.values():
        beat_segments: list[list[TokenTiming]] = []
        current: list[TokenTiming] = []
        for token in beat_tokens:
            candidate = "".join(item.text for item in current) + token.text
            if current and fullwidth_units(candidate) > hard_units:
                beat_segments.append(current)
                current = []
            current.append(token)
            text = "".join(item.text for item in current)
            if token.text and token.text[-1] in BREAK_PUNCTUATION and fullwidth_units(text) >= 4.0:
                beat_segments.append(current)
                current = []
        if current:
            beat_segments.append(current)

        if len(beat_segments) >= 2:
            previous = beat_segments[-2]
            tail = beat_segments[-1]
            while fullwidth_units("".join(item.text for item in tail)) < 4.0 and len(previous) > 1:
                candidate = previous[-1:] + tail
                remaining = previous[:-1]
                if fullwidth_units("".join(item.text for item in candidate)) > hard_units:
                    break
                if fullwidth_units("".join(item.text for item in remaining)) < 4.0:
                    break
                tail.insert(0, previous.pop())
        segments.extend(beat_segments)

    cues: list[SubtitleCue] = []
    for segment in segments:
        text = "".join(token.text for token in segment).strip()
        if text and fullwidth_units(text) > hard_units + 1e-6:
            raise ValueError(f"subtitle exceeds {hard_units} fullwidth units: {text}")
        cues.append(
            SubtitleCue(
                cue_id=f"sub_{len(cues) + 1:03d}",
                text=text,
                start_frame=segment[0].start_frame,
                end_frame=segment[-1].end_frame,
                slot=default_slot,
                emphasize=_emphasis(segment, timing.phrase_anchors),
                beat_id=segment[0].beat_id,
            )
        )
    if any("\n" in cue.text or "\r" in cue.text for cue in cues):
        raise ValueError("subtitle compiler produced a multiline cue")
    return cues
