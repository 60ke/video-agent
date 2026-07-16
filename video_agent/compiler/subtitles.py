from __future__ import annotations

import unicodedata

from video_agent.contracts import GalleryItem, PhraseAnchor, SubtitleCue, TimingLock, TokenTiming


BREAK_PUNCTUATION = set("，。！？；：")
ORPHAN_CONNECTORS = {"从", "到", "和", "及", "与", "以及"}


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


def _compact(text: str) -> str:
    return "".join(char for char in text if not char.isspace())


def _gallery_tokens(tokens: list[TokenTiming], start_index: int, phrase: str) -> tuple[list[TokenTiming], int]:
    expected = _compact(phrase)
    collected: list[TokenTiming] = []
    for index in range(start_index, len(tokens)):
        collected.append(tokens[index])
        actual = _compact("".join(token.text for token in collected))
        if actual == expected:
            return collected, index + 1
        if not expected.startswith(actual):
            break
    raise ValueError(f"gallery phrase does not match tokens at {tokens[start_index].token_id}: {phrase}")


def _gallery_starts(timing: TimingLock, gallery_items: list[GalleryItem]) -> dict[str, GalleryItem]:
    token_ids = {token.token_id for token in timing.tokens}
    phrase_anchors = {anchor.anchor_id: anchor for anchor in timing.phrase_anchors}
    starts: dict[str, GalleryItem] = {}
    for item in gallery_items:
        if item.anchor_id in token_ids:
            start_token_id = item.anchor_id
        elif item.anchor_id in phrase_anchors:
            start_token_id = phrase_anchors[item.anchor_id].token_ids[0]
        else:
            raise ValueError(f"gallery item references unknown timing anchor: {item.anchor_id}")
        if start_token_id in starts:
            raise ValueError(f"multiple gallery subtitles share one token anchor: {start_token_id}")
        starts[start_token_id] = item
    return starts


def compile_subtitles(
    timing: TimingLock,
    default_slot: str = "subtitle_top",
    *,
    max_width_px: int = 856,
    minimum_font_px: int = 48,
    gallery_items: list[GalleryItem] | None = None,
) -> list[SubtitleCue]:
    """Build single-line cues from punctuation and the actual render width.

    Ten Chinese characters is a useful editorial rhythm, not a layout law.
    The compiler therefore only forces a break when text cannot fit at the
    renderer's minimum subtitle size.
    """

    max_units = max_width_px / minimum_font_px
    forced_by_token = _gallery_starts(timing, gallery_items or [])
    by_beat: dict[str | None, list[TokenTiming]] = {}
    for token in timing.tokens:
        by_beat.setdefault(token.beat_id, []).append(token)

    segments: list[tuple[list[TokenTiming], str, str | None]] = []
    for beat_tokens in by_beat.values():
        beat_segments: list[tuple[list[TokenTiming], str, str | None]] = []
        current: list[TokenTiming] = []
        index = 0
        while index < len(beat_tokens):
            token = beat_tokens[index]
            forced = forced_by_token.get(token.token_id)
            if forced:
                if current:
                    pending = "".join(item.text for item in current).strip(" ，、。！？；：")
                    if pending and pending not in ORPHAN_CONNECTORS:
                        beat_segments.append((current, "default", None))
                    current = []
                group, index = _gallery_tokens(beat_tokens, index, forced.phrase)
                beat_segments.append((group, "gallery_yellow", forced.phrase.strip()))
                continue
            candidate = "".join(item.text for item in current) + token.text
            if current and fullwidth_units(candidate) > max_units:
                beat_segments.append((current, "default", None))
                current = []
            current.append(token)
            text = "".join(item.text for item in current)
            if token.text and token.text[-1] in BREAK_PUNCTUATION and fullwidth_units(text) >= 4.0:
                beat_segments.append((current, "default", None))
                current = []
            index += 1
        if current:
            beat_segments.append((current, "default", None))
        segments.extend(beat_segments)

    cues: list[SubtitleCue] = []
    for segment, style, text_override in segments:
        text = text_override or "".join(token.text for token in segment).strip(" ，、。！？；：")
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
                emphasize=text if style == "gallery_yellow" else _emphasis(segment, timing.phrase_anchors),
                beat_id=segment[0].beat_id,
                style=style,
            )
        )
    if any("\n" in cue.text or "\r" in cue.text for cue in cues):
        raise ValueError("subtitle compiler produced a multiline cue")
    return cues
