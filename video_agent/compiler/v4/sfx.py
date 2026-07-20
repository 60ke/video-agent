"""Stage6 SFX arbitration and peak alignment (no sfx_id replacement)."""

from __future__ import annotations

import wave
from pathlib import Path

from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    CompiledAudioTrackV4,
    MotionAudioPlan,
    SfxEntry,
    SfxIntent,
    SfxProfileEntry,
    SpeechTimingLock,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.registries import CapabilityRegistryHub
from video_agent.timing.v4.timebase import ms_to_hit_frame


def compile_sfx_tracks(
    *,
    motion_plan: MotionAudioPlan,
    anchored: AnchoredTimingPlan,
    speech: SpeechTimingLock,
    registry: CapabilityRegistryHub,
    repo_root: Path,
    peak_tolerance_frames: int = 1,
) -> tuple[list[CompiledAudioTrackV4], list[dict]]:
    profile_entry = registry.entry("sfx_profile", motion_plan.sfx_profile.profile_id)
    if not isinstance(profile_entry, SfxProfileEntry):
        raise Stage6Error("sfx_peak_tolerance_exceeded", "sfx profile missing")
    profile = profile_entry.capabilities

    anchors = {item.anchor_id: item for item in anchored.anchors}
    # Map intents to anchors via phrase + scene
    phrase_bindings = [
        b for b in anchored.bindings if b.binding_kind in {"sfx_intent", "operation", "effect_event", "slot"}
    ]

    audited: list[dict] = []
    kept_intents: list[tuple[SfxIntent, str]] = []  # intent, anchor_id

    for intent in motion_plan.sfx_intents:
        anchor_id = _resolve_intent_anchor(intent, anchored, phrase_bindings)
        if anchor_id is None:
            audited.append({"intent_id": intent.intent_id, "action": "suppress", "reason": "anchor_unresolved"})
            continue
        kept_intents.append((intent, anchor_id))

    # Time-window density / cooldown arbitration
    decisions = _arbitrate(kept_intents, anchors, profile, speech.fps)
    tracks: list[CompiledAudioTrackV4] = []

    for intent, anchor_id, action, gain_adjust in decisions:
        audited.append({"intent_id": intent.intent_id, "action": action, "anchor_id": anchor_id})
        if action == "suppress":
            continue
        entry = registry.entry("sfx", intent.sfx_id)
        if not isinstance(entry, SfxEntry):
            raise Stage6Error("sfx_peak_tolerance_exceeded", f"unknown sfx {intent.sfx_id}")
        caps = entry.capabilities
        anchor = anchors[anchor_id]
        configured_offset = caps.sync_offset_ms
        desired_start_ms = anchor.onset_ms - configured_offset
        trim_start = caps.trim_start_ms
        effective_offset = configured_offset
        if desired_start_ms < 0:
            extra = abs(desired_start_ms)
            trim_start = caps.trim_start_ms + extra
            effective_offset = configured_offset - extra
            start_frame = 0
        else:
            start_frame = ms_to_hit_frame(desired_start_ms, speech.fps)

        wav_path = repo_root / caps.relative_path
        peak_ms = measure_wav_peak_ms(wav_path)
        # Peak lands at start_ms + (peak_ms - trim_start) roughly
        actual_peak_ms = max(0, start_frame * 1000 // speech.fps) + max(0, peak_ms - trim_start)
        expected_peak_frame = ms_to_hit_frame(actual_peak_ms, speech.fps)
        if abs(expected_peak_frame - anchor.hit_frame) > peak_tolerance_frames:
            # Prefer adjusting start when within reason; else fail-loud
            delta_frames = expected_peak_frame - anchor.hit_frame
            start_frame = max(0, start_frame - delta_frames)
            actual_peak_ms = max(0, start_frame * 1000 // speech.fps) + max(0, peak_ms - trim_start)
            expected_peak_frame = ms_to_hit_frame(actual_peak_ms, speech.fps)
            if abs(expected_peak_frame - anchor.hit_frame) > peak_tolerance_frames:
                raise Stage6Error(
                    "sfx_peak_tolerance_exceeded",
                    (
                        f"sfx {intent.sfx_id} peak frame {expected_peak_frame} "
                        f"vs hit {anchor.hit_frame}"
                    ),
                    scene_id=intent.scene_id,
                    anchor_id=anchor_id,
                    details={
                        "expected_peak_frame": expected_peak_frame,
                        "hit_frame": anchor.hit_frame,
                    },
                )

        gain = caps.gain_db + gain_adjust
        tracks.append(
            CompiledAudioTrackV4(
                track_id=f"sfx://{intent.intent_id}",
                kind="sfx",
                object_key=caps.relative_path,
                sha256=caps.content_sha256,
                start_frame=start_frame,
                gain_db=gain,
                anchor_id=anchor_id,
                semantic_id=intent.sfx_id,
                hit_frame=anchor.hit_frame,
                configured_sync_offset_ms=configured_offset,
                effective_sync_offset_ms=effective_offset,
                trim_start_ms=trim_start,
                expected_peak_frame=expected_peak_frame,
                max_duration_ms=caps.max_duration_ms,
                fade_in_ms=caps.fade_in_ms,
                fade_out_ms=caps.fade_out_ms,
            )
        )
    return tracks, audited


def _resolve_intent_anchor(
    intent: SfxIntent,
    anchored: AnchoredTimingPlan,
    phrase_bindings: list,
) -> str | None:
    # Prefer binding with matching source
    for binding in phrase_bindings:
        if binding.scene_id != intent.scene_id:
            continue
        anchor = next(a for a in anchored.anchors if a.anchor_id == binding.anchor_id)
        if anchor.text == intent.anchor_phrase:
            return binding.anchor_id
    for anchor in anchored.anchors:
        if anchor.scene_id == intent.scene_id and anchor.text == intent.anchor_phrase:
            return anchor.anchor_id
    return None


def _arbitrate(
    items: list[tuple[SfxIntent, str]],
    anchors: dict,
    profile,
    fps: int,
) -> list[tuple[SfxIntent, str, str, float]]:
    """Return (intent, anchor_id, action, gain_adjust_db)."""
    ordered = sorted(
        items,
        key=lambda pair: (
            0 if pair[0].source_kind == "operation_semantic" else 1,
            -pair[0].priority,
            anchors[pair[1]].hit_frame,
            pair[0].intent_id,
        ),
    )
    accepted: list[tuple[SfxIntent, str, int]] = []  # intent, anchor, onset_ms
    results: list[tuple[SfxIntent, str, str, float]] = []
    window_ms = profile.window_ms
    budget = profile.window_event_budget
    min_interval = profile.min_interval_ms
    cooldown = profile.same_kind_cooldown_ms

    for intent, anchor_id in ordered:
        onset = anchors[anchor_id].onset_ms
        # same-kind cooldown
        conflict = False
        for prev_intent, _prev_anchor, prev_onset in accepted:
            if abs(onset - prev_onset) < min_interval:
                conflict = True
                break
            if intent.sfx_id == prev_intent.sfx_id and abs(onset - prev_onset) < cooldown:
                conflict = True
                break
        # window budget
        window_count = sum(1 for _, _, prev_onset in accepted if abs(onset - prev_onset) <= window_ms // 2)
        if budget >= 0 and window_count >= budget:
            conflict = True

        if conflict:
            action = profile.conflict_action
            if action == "attenuate":
                results.append((intent, anchor_id, "attenuate", -6.0))
                accepted.append((intent, anchor_id, onset))
            else:
                results.append((intent, anchor_id, "suppress", 0.0))
        else:
            results.append((intent, anchor_id, "keep", 0.0))
            accepted.append((intent, anchor_id, onset))
    _ = fps
    return results


def measure_wav_peak_ms(path: Path) -> int:
    if not path.is_file():
        raise Stage6Error(
            "media_decode_preflight_failed",
            f"sfx wav missing: {path}",
        )
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        # Fallback: use midpoint
        return 0
    import array

    samples = array.array("h")
    samples.frombytes(frames)
    peak_index = 0
    peak_value = -1
    step = max(channels, 1)
    for index in range(0, len(samples), step):
        value = abs(samples[index])
        if value > peak_value:
            peak_value = value
            peak_index = index // step
    return int(round(peak_index * 1000 / rate))


def compile_voice_track(speech: SpeechTimingLock) -> CompiledAudioTrackV4:
    return CompiledAudioTrackV4(
        track_id="voice://main",
        kind="voice",
        object_key=speech.audio_object_key,
        sha256=speech.audio_sha256,
        start_frame=0,
        gain_db=0.0,
        anchor_id=None,
        semantic_id="voice",
        hit_frame=None,
        configured_sync_offset_ms=0,
        effective_sync_offset_ms=0,
        trim_start_ms=0,
        expected_peak_frame=None,
        max_duration_ms=speech.duration_ms,
        fade_in_ms=0,
        fade_out_ms=0,
    )
