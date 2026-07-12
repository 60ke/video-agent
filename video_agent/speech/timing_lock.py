from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from video_agent.contracts import BeatSpan, Narration, PauseEvent, PhraseAnchor, TimingLock, TokenTiming
from video_agent.io import sha256_file


SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    compact = SPACE_RE.sub("", text).lower()
    return "".join(char for char in compact if not unicodedata.category(char).startswith("P"))


def _display_slices(text: str, lexical_lengths: list[int]) -> list[str]:
    compact = SPACE_RE.sub("", text)
    lexical_total = sum(1 for char in compact if not unicodedata.category(char).startswith("P"))
    if sum(lexical_lengths) != lexical_total:
        raise ValueError("word timing lexical lengths do not match narration")
    slices: list[str] = []
    display_cursor = 0
    lexical_cursor = 0
    for length in lexical_lengths:
        target = lexical_cursor + length
        index = display_cursor
        seen = lexical_cursor
        while index < len(compact) and seen < target:
            if not unicodedata.category(compact[index]).startswith("P"):
                seen += 1
            index += 1
        while index < len(compact) and unicodedata.category(compact[index]).startswith("P"):
            index += 1
        slices.append(compact[display_cursor:index])
        display_cursor = index
        lexical_cursor = target
    if display_cursor != len(compact):
        raise ValueError("word timing could not recover narration punctuation")
    return slices


def ms_to_frame(milliseconds: int, fps: int) -> int:
    value = Decimal(milliseconds) * Decimal(fps) / Decimal(1000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _anchor_id(beat_id: str, phrase: str) -> str:
    digest = hashlib.sha256(f"{beat_id}|{phrase}".encode("utf-8")).hexdigest()[:10]
    return f"anchor_{digest}"


def build_timing_lock(
    case_id: str,
    narration: Narration,
    raw_tokens: list[dict[str, Any]],
    audio_path: Path,
    duration_ms: int,
    fps: int,
) -> TimingLock:
    if not raw_tokens:
        raise ValueError("Minimax word timing is empty")
    lexical_raw_tokens: list[dict[str, Any]] = []
    for item in raw_tokens:
        if normalize_text(str(item.get("text") or "")):
            lexical_raw_tokens.append(dict(item))
        elif lexical_raw_tokens:
            lexical_raw_tokens[-1]["end_ms"] = max(
                int(lexical_raw_tokens[-1].get("end_ms") or 0),
                int(item.get("end_ms") or 0),
            )
    expected = normalize_text(narration.spoken_text)
    actual = "".join(normalize_text(str(item.get("text") or "")) for item in lexical_raw_tokens)
    if actual != expected:
        raise ValueError(f"Minimax word timing text mismatch: expected {expected!r}, got {actual!r}")
    display_slices = _display_slices(
        narration.spoken_text,
        [len(normalize_text(str(item.get("text") or ""))) for item in lexical_raw_tokens],
    )

    beat_boundaries: list[tuple[str, int, int]] = []
    cursor = 0
    for beat in narration.beats:
        length = len(normalize_text(beat.spoken_text))
        beat_boundaries.append((beat.beat_id, cursor, cursor + length))
        cursor += length

    tokens: list[TokenTiming] = []
    token_char_spans: list[tuple[int, int]] = []
    char_cursor = 0
    previous_end = 0
    for idx, (raw, text) in enumerate(zip(lexical_raw_tokens, display_slices)):
        normalized = normalize_text(text)
        start_ms = int(raw.get("start_ms") or 0)
        end_ms = int(raw.get("end_ms") or 0)
        if start_ms < previous_end or end_ms <= start_ms or end_ms > duration_ms + 100:
            raise ValueError(f"invalid Minimax token timing at index {idx}: {start_ms}-{end_ms}")
        span = (char_cursor, char_cursor + len(normalized))
        token_char_spans.append(span)
        char_cursor = span[1]
        beat_id = next((bid for bid, start, end in beat_boundaries if start <= span[0] < end), None)
        start_frame = ms_to_frame(start_ms, fps)
        end_frame = max(start_frame + 1, ms_to_frame(end_ms, fps))
        tokens.append(
            TokenTiming(
                token_id=f"tok_{idx + 1:04d}",
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                start_frame=start_frame,
                end_frame=end_frame,
                beat_id=beat_id,
            )
        )
        previous_end = end_ms

    beat_spans: list[BeatSpan] = []
    for beat_id, _, _ in beat_boundaries:
        beat_tokens = [token for token in tokens if token.beat_id == beat_id]
        if not beat_tokens:
            raise ValueError(f"beat has no timing tokens: {beat_id}")
        beat_spans.append(
            BeatSpan(
                beat_id=beat_id,
                token_ids=[token.token_id for token in beat_tokens],
                start_frame=beat_tokens[0].start_frame,
                end_frame=beat_tokens[-1].end_frame,
            )
        )

    phrase_anchors: list[PhraseAnchor] = []
    pause_events: list[PauseEvent] = []
    for beat in narration.beats:
        beat_indices = [idx for idx, token in enumerate(tokens) if token.beat_id == beat.beat_id]
        local_tokens = [tokens[idx] for idx in beat_indices]
        local_text = "".join(normalize_text(token.text) for token in local_tokens)
        local_offsets: list[tuple[int, int]] = []
        local_cursor = 0
        for token in local_tokens:
            size = len(normalize_text(token.text))
            local_offsets.append((local_cursor, local_cursor + size))
            local_cursor += size
        for phrase in beat.hit_phrases:
            normalized_phrase = normalize_text(phrase)
            start = local_text.find(normalized_phrase)
            if start < 0:
                raise ValueError(f"hit phrase not found in {beat.beat_id}: {phrase}")
            end = start + len(normalized_phrase)
            matched = [token for token, span in zip(local_tokens, local_offsets) if span[1] > start and span[0] < end]
            phrase_anchors.append(
                PhraseAnchor(
                    anchor_id=_anchor_id(beat.beat_id, phrase),
                    text=phrase,
                    token_ids=[token.token_id for token in matched],
                    hit_frame=matched[0].start_frame,
                    beat_id=beat.beat_id,
                )
            )
        for pause_idx, pause in enumerate(beat.pause_intents):
            normalized_phrase = normalize_text(pause.after_phrase)
            start = local_text.find(normalized_phrase)
            if start < 0:
                raise ValueError(f"pause phrase not found in {beat.beat_id}: {pause.after_phrase}")
            end = start + len(normalized_phrase)
            matched_indexes = [idx for idx, span in enumerate(local_offsets) if span[1] > start and span[0] < end]
            last_local_idx = matched_indexes[-1]
            after_token = local_tokens[last_local_idx]
            next_token = local_tokens[last_local_idx + 1] if last_local_idx + 1 < len(local_tokens) else None
            measured_start = after_token.end_frame
            measured_end = next_token.start_frame if next_token else measured_start
            pause_events.append(
                PauseEvent(
                    pause_id=f"pause_{beat.beat_id}_{pause_idx + 1:02d}",
                    after_token_id=after_token.token_id,
                    requested_ms=pause.requested_ms,
                    measured_start_frame=measured_start,
                    measured_end_frame=max(measured_start, measured_end),
                )
            )

    duration_frames = max(ms_to_frame(duration_ms, fps), tokens[-1].end_frame)
    return TimingLock(
        case_id=case_id,
        audio_path=audio_path.as_posix(),
        audio_sha256=sha256_file(audio_path),
        fps=fps,
        duration_ms=duration_ms,
        duration_frames=duration_frames,
        tokens=tokens,
        phrase_anchors=phrase_anchors,
        pause_events=pause_events,
        beat_spans=beat_spans,
    )
