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


def compile_subtitles(
    timing: TimingLock,
    default_slot: str = "subtitle_top",
    *,
    max_width_px: int = 856,
    minimum_font_px: int = 48,
    gallery_anchor_ids: set[str] | None = None,
) -> list[SubtitleCue]:
    """Build single-line cues from punctuation and the actual render width.

    Ten Chinese characters is a useful editorial rhythm, not a layout law.
    The compiler therefore only forces a break when text cannot fit at the
    renderer's minimum subtitle size.
    """

    max_units = max_width_px / minimum_font_px
    gallery_anchor_ids = gallery_anchor_ids or set()
    forced_anchors = {anchor.anchor_id: anchor for anchor in timing.phrase_anchors if anchor.anchor_id in gallery_anchor_ids}
    forced_by_token = {
        token_id: anchor
        for anchor in forced_anchors.values()
        for token_id in anchor.token_ids
    }
    by_beat: dict[str | None, list[TokenTiming]] = {}
    for token in timing.tokens:
        by_beat.setdefault(token.beat_id, []).append(token)

    segments: list[tuple[list[TokenTiming], str]] = []
    for beat_tokens in by_beat.values():
        beat_segments: list[tuple[list[TokenTiming], str]] = []
        current: list[TokenTiming] = []
        index = 0
        while index < len(beat_tokens):
            token = beat_tokens[index]
            forced = forced_by_token.get(token.token_id)
            if forced:
                if current:
                    beat_segments.append((current, "default"))
                    current = []
                forced_ids = set(forced.token_ids)
                group = [item for item in beat_tokens if item.token_id in forced_ids]
                if not any(style == "gallery_yellow" and segment and segment[0].token_id == group[0].token_id for segment, style in beat_segments):
                    beat_segments.append((group, "gallery_yellow"))
                index += 1
                continue
            candidate = "".join(item.text for item in current) + token.text
            if current and fullwidth_units(candidate) > max_units:
                beat_segments.append((current, "default"))
                current = []
            current.append(token)
            text = "".join(item.text for item in current)
            if token.text and token.text[-1] in BREAK_PUNCTUATION and fullwidth_units(text) >= 4.0:
                beat_segments.append((current, "default"))
                current = []
            index += 1
        if current:
            beat_segments.append((current, "default"))
        segments.extend(beat_segments)

    cues: list[SubtitleCue] = []
    for segment, style in segments:
        text = "".join(token.text for token in segment).strip(" ，、。！？；：")
        if not text:
            continue
        if text and fullwidth_units(text) > max_units + 1e-6:
            raise ValueError(f"subtitle cannot fit the configured slot: {text}")
        cues.append(
            SubtitleCue(
                cue_id=f"sub_{len(cues) + 1:03d}",
                text=text,
                start_frame=segment[0].start_frame,
                end_frame=segment[-1].end_frame,
                slot=default_slot,
                emphasize=_emphasis(segment, timing.phrase_anchors),
                beat_id=segment[0].beat_id,
                style=style,
            )
        )
    if any("\n" in cue.text or "\r" in cue.text for cue in cues):
        raise ValueError("subtitle compiler produced a multiline cue")
    return cues
