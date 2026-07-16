from __future__ import annotations

import colorsys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from video_agent.audio import merge_sfx_profile
from video_agent.compiler.evidence import validate_claim_bindings
from video_agent.compiler.subtitles import compile_subtitles
from video_agent.contracts import (
    AssetCatalog,
    AudioConfig,
    AudioTrack,
    CompiledCue,
    CompiledEditorFlowSequence,
    CompiledGalleryItem,
    CompiledParameterFrameSequence,
    DurationPolicy,
    Narration,
    RenderAsset,
    RenderPlan,
    RenderShot,
    TimingLock,
    VisualPlan,
)
from video_agent.planning.parameter_sequence import compile_parameter_sequence_timing
from video_agent.platform import get_profile


MOTION_ALLOWLIST = {
    "none",
    "fade_in",
    "fade_out",
    "scale_in",
    "scale_out",
    "image_pan_scan",
    "detail_push_in",
    "result_reveal",
    "full_bleed_to_safe_card",
    "page_turn_3d",
    "card_flip_3d",
    "paper_curl_flip",
    "brand_breath",
    "film_strip",
    "grid_reveal",
    "vertical_scroll",
    "before_after",
    "slide_gallery",
    "card_stack",
    "light_sweep",
}
TEMPLATE_ALLOWLIST = {"ui_params_focus", "ui_feature_entry", "editor_interaction", "result_showcase", "brand_ip_cutaway", "reference_to_result"}
TEXT_DENSE_TEMPLATES = {"ui_params_focus"}
TEXT_DENSE_MOTION_ALLOWLIST = {"none", "fade_in", "fade_out", "scale_in", "scale_out"}
BEAT_START_ANCHOR_PREFIX = "beat_start:"
BEAT_END_ANCHOR_PREFIX = "beat_end:"
TIMELINE_START_ANCHOR = "timeline_start"
TIMELINE_END_ANCHOR = "timeline_end"


def _accent_color(path: Path) -> str | None:
    """Choose a stable saturated palette color for a picture-led entrance."""

    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((96, 96))
            palette = image.quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert("RGB")
            colors = palette.getcolors(maxcolors=96 * 96) or []
    except OSError:
        return None
    best: tuple[float, tuple[float, float, float]] | None = None
    for count, rgb in colors:
        red, green, blue = rgb
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if value < 0.22 or saturation < 0.20:
            continue
        score = count * saturation**2 * (0.45 + value)
        if best is None or score > best[0]:
            best = (score, (hue, saturation, value))
    if best is None:
        return None
    hue, saturation, value = best[1]
    red, green, blue = colorsys.hsv_to_rgb(hue, max(0.62, saturation), max(0.82, value))
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


@dataclass(frozen=True)
class _SfxEvent:
    semantic_id: str
    anchor_id: str
    hit_frame: int
    start_frame: int
    sync_point: str
    effective_sync_offset_ms: int
    path: str
    gain_db: float
    trim_start_ms: int
    max_duration_ms: int
    fade_in_ms: int
    fade_out_ms: int
    priority: int


def _resolve_sfx_path(path: str, case_dir: Path, repo_root: Path) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw.resolve()
    candidates = [repo_root / raw, case_dir / raw] if raw.parts and raw.parts[0] == "assets" else [case_dir / raw, repo_root / raw]
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), candidates[0].resolve())


def _select_sfx_events(events: list[_SfxEvent], fps: int, audio: AudioConfig) -> list[_SfxEvent]:
    policy = audio.sfx_density
    ranked = sorted(events, key=lambda item: (item.hit_frame, -item.priority, item.semantic_id))
    selected: list[_SfxEvent] = []
    for event in ranked:
        event_ms = event.hit_frame * 1000 / fps
        if policy.min_gap_ms is not None and any(abs(event_ms - chosen.hit_frame * 1000 / fps) < policy.min_gap_ms for chosen in selected):
            continue
        if policy.repeat_cooldown_ms is not None and any(
            chosen.semantic_id == event.semantic_id
            and abs(event_ms - chosen.hit_frame * 1000 / fps) < policy.repeat_cooldown_ms
            for chosen in selected
        ):
            continue
        events_in_window = sum(1 for chosen in selected if policy.window_ms is not None and abs(event_ms - chosen.hit_frame * 1000 / fps) < policy.window_ms)
        if policy.max_events_per_window is not None and events_in_window >= policy.max_events_per_window:
            continue
        selected.append(event)
    return sorted(selected, key=lambda item: (item.start_frame, item.semantic_id))


def _timing_anchors(timing: TimingLock) -> dict[str, int]:
    anchors = {
        TIMELINE_START_ANCHOR: 0,
        TIMELINE_END_ANCHOR: timing.duration_frames,
        **{anchor.anchor_id: int(anchor.onset_frame) for anchor in timing.phrase_anchors},
        **{token.token_id: token.start_frame for token in timing.tokens},
    }
    for span in timing.beat_spans:
        anchors[f"{BEAT_START_ANCHOR_PREFIX}{span.beat_id}"] = span.start_frame
        anchors[f"{BEAT_END_ANCHOR_PREFIX}{span.beat_id}"] = span.end_frame
    return anchors


def _resolve_time(anchor_frames: dict[str, int], anchor_id: str, offset_frames: int, duration_frames: int) -> int:
    if anchor_id not in anchor_frames:
        raise ValueError(f"shot references unknown timing anchor: {anchor_id}")
    return max(0, min(duration_frames, anchor_frames[anchor_id] + offset_frames))


def _validate_claim_timing(narration: Narration, timing: TimingLock, shots: list[RenderShot]) -> None:
    anchors = {(anchor.beat_id, claim_id): anchor for anchor in timing.phrase_anchors for claim_id in anchor.claim_ids}
    for beat in narration.beats:
        for cue in beat.claim_cues:
            anchor = anchors.get((beat.beat_id, cue.claim_id))
            if anchor is None:
                raise ValueError(f"claim cue has no timing anchor: {beat.beat_id}/{cue.claim_id}")
            visible = any(
                shot.track == "base"
                and cue.claim_id in shot.claim_ids
                and shot.start_frame <= anchor.hit_frame < shot.end_frame
                for shot in shots
            )
            if not visible:
                raise ValueError(
                    f"claim {cue.claim_id} is not visibly supported at frame {anchor.hit_frame} in {beat.beat_id}"
                )


def compile_render_plan(
    case_id: str,
    run_id: str,
    narration: Narration,
    timing: TimingLock,
    visual: VisualPlan,
    catalog: AssetCatalog,
    repo_root: Path,
    platform_profile: str,
    width: int,
    height: int,
    case_dir: Path,
    audio: AudioConfig,
    duration_policy: DurationPolicy,
) -> RenderPlan:
    if narration.case_id != case_id or visual.case_id != case_id or timing.case_id != case_id:
        raise ValueError("case ids differ across narration, timing, and visual contracts")
    if width != 1080 or height != 1920:
        raise ValueError("V3 currently renders only the douyin_portrait_v1 1080x1920 canvas")

    beat_ids = {beat.beat_id for beat in narration.beats}
    anchor_by_id = {anchor.anchor_id: anchor for anchor in timing.phrase_anchors}
    anchor_frames = _timing_anchors(timing)
    asset_by_id = {asset.asset_id: asset for asset in catalog.assets}
    validate_claim_bindings(narration, visual, asset_by_id)

    audio_tracks = [
        AudioTrack(kind="voice", path=str(Path(timing.audio_path).resolve()), start_frame=0, gain_db=audio.voice_gain_db)
    ]
    if audio.bgm_path:
        bgm_path = (case_dir / audio.bgm_path).resolve()
        if not bgm_path.is_file():
            raise FileNotFoundError(f"BGM source is missing: {bgm_path}")
        audio_tracks.append(AudioTrack(kind="bgm", path=bgm_path.as_posix(), gain_db=audio.bgm_gain_db, loop=True, duck_under_voice=True))

    sfx_profile = merge_sfx_profile(audio.sfx_profile, audio.sfx_overrides)
    render_shots: list[RenderShot] = []
    sfx_events: list[_SfxEvent] = []
    used_asset_ids: set[str] = set()
    for shot in visual.shots:
        unknown_beats = set(shot.beat_ids) - beat_ids
        if unknown_beats:
            raise ValueError(f"shot references unknown beats: {sorted(unknown_beats)}")
        if shot.motion not in MOTION_ALLOWLIST:
            raise ValueError(f"motion is not allowed in V3: {shot.motion}")
        if shot.template not in TEMPLATE_ALLOWLIST:
            raise ValueError(f"template is not implemented in V3: {shot.template}")
        if shot.template == "reference_to_result" and set(shot.asset_bindings) != {"input", "output"}:
            raise ValueError(f"causal scenes require exactly input and output bindings: {shot.shot_id}")
        if shot.template in TEXT_DENSE_TEMPLATES and shot.motion not in TEXT_DENSE_MOTION_ALLOWLIST:
            raise ValueError(f"motion {shot.motion!r} distorts text-dense template {shot.template!r}")
        missing_assets = [asset_id for asset_id in shot.asset_ids if asset_id not in asset_by_id]
        if missing_assets:
            raise ValueError(f"shot references missing assets: {missing_assets}")
        ineligible = [asset_id for asset_id in shot.asset_ids if not asset_by_id[asset_id].production_eligible]
        if ineligible:
            raise ValueError(f"shot references source-only assets: {ineligible}")

        start_frame = _resolve_time(anchor_frames, shot.start.anchor_id, shot.start.offset_frames, timing.duration_frames)
        end_frame = _resolve_time(anchor_frames, shot.end.anchor_id, shot.end.offset_frames, timing.duration_frames)
        if end_frame <= start_frame:
            raise ValueError(f"shot has non-positive resolved duration: {shot.shot_id}")
        cues: list[CompiledCue] = []
        for binding in shot.cue_bindings:
            anchor = anchor_by_id.get(binding.anchor_id)
            token = next((item for item in timing.tokens if item.token_id == binding.anchor_id), None)
            is_beat_boundary = binding.anchor_id in anchor_frames and (
                binding.anchor_id.startswith(BEAT_START_ANCHOR_PREFIX) or binding.anchor_id.startswith(BEAT_END_ANCHOR_PREFIX)
            )
            if anchor is None and token is None and not is_beat_boundary:
                raise ValueError(f"shot references unknown phrase anchor: {binding.anchor_id}")
            if anchor is not None and anchor.beat_id not in shot.beat_ids:
                raise ValueError(f"cue anchor belongs to a beat outside {shot.shot_id}: {binding.anchor_id}")
            if token is not None and token.beat_id not in shot.beat_ids:
                raise ValueError(f"cue token belongs to a beat outside {shot.shot_id}: {binding.anchor_id}")
            hit_frame = max(0, min(timing.duration_frames, anchor_frames[binding.anchor_id] + binding.offset_frames))
            if hit_frame < start_frame or hit_frame > end_frame:
                raise ValueError(f"cue anchor falls outside shot range: {binding.anchor_id}")
            cues.append(CompiledCue(action=binding.action, anchor_id=binding.anchor_id, hit_frame=hit_frame))
            if binding.sfx:
                source = sfx_profile.get(binding.sfx)
                if not source:
                    raise ValueError(f"SFX cue has no configured source: {binding.sfx}")
                path = _resolve_sfx_path(source.path, case_dir, repo_root)
                if not path.is_file():
                    raise FileNotFoundError(f"SFX source is missing: {path}")
                hit_ms = hit_frame * 1000 / timing.fps
                desired_start_ms = hit_ms - source.sync_offset_ms
                extra_trim_ms = max(0, round(-desired_start_ms))
                effective_sync_offset_ms = max(0, source.sync_offset_ms - extra_trim_ms)
                sfx_start_frame = max(0, round(max(0.0, desired_start_ms) * timing.fps / 1000))
                sfx_events.append(
                    _SfxEvent(
                        semantic_id=binding.sfx,
                        anchor_id=binding.anchor_id,
                        hit_frame=hit_frame,
                        start_frame=sfx_start_frame,
                        sync_point=source.sync_point,
                        effective_sync_offset_ms=effective_sync_offset_ms,
                        path=path.as_posix(),
                        gain_db=source.gain_db,
                        trim_start_ms=source.trim_start_ms + extra_trim_ms,
                        max_duration_ms=source.max_duration_ms,
                        fade_in_ms=source.fade_in_ms,
                        fade_out_ms=source.fade_out_ms,
                        priority=source.priority,
                    )
                )
        compiled_sequence = None
        if shot.parameter_sequence:
            sequence = shot.parameter_sequence
            expected = {
                "base": sequence.base_asset_id,
                "stage": sequence.stage_asset_id,
                "final": sequence.final_asset_id,
            }
            if shot.asset_bindings != expected:
                raise ValueError(f"parameter sequence bindings do not match sequence contract: {shot.shot_id}")
            timing_result = compile_parameter_sequence_timing(
                required_field_labels=sequence.required_field_labels,
                anchors=[anchor for anchor in timing.phrase_anchors if anchor.beat_id in shot.beat_ids],
                shot_start_frame=start_frame,
                shot_end_frame=end_frame,
            )
            compiled_sequence = CompiledParameterFrameSequence(
                sequence_id=sequence.sequence_id,
                base_asset_id=sequence.base_asset_id,
                stage_asset_id=sequence.stage_asset_id,
                final_asset_id=sequence.final_asset_id,
                required_field_labels=sequence.required_field_labels,
                callout_text=sequence.callout_text,
                callout_reveal_frames=sequence.callout_reveal_frames,
                **timing_result.__dict__,
            )
        compiled_editor_flow = None
        if shot.editor_flow_sequence:
            sequence = shot.editor_flow_sequence
            focus_frame = _resolve_time(anchor_frames, sequence.focus_anchor_id, 0, timing.duration_frames)
            modal_frame = _resolve_time(anchor_frames, sequence.modal_anchor_id, 0, timing.duration_frames)
            if not start_frame <= focus_frame < end_frame or not start_frame <= modal_frame < end_frame:
                raise ValueError(f"editor flow anchors fall outside shot range: {shot.shot_id}")
            compiled_editor_flow = CompiledEditorFlowSequence(
                sequence_id=sequence.sequence_id,
                page_asset_id=sequence.page_asset_id,
                modal_asset_id=sequence.modal_asset_id,
                focus_frame=focus_frame,
                modal_frame=modal_frame,
                focus_x=sequence.focus_x,
                focus_y=sequence.focus_y,
                focus_w=sequence.focus_w,
                focus_h=sequence.focus_h,
                lens_zoom=sequence.lens_zoom,
                reveal_frames=sequence.reveal_frames,
            )
        compiled_gallery_items = []
        for item in shot.gallery_items:
            if item.anchor_id not in anchor_frames:
                raise ValueError(f"gallery item references unknown phrase anchor: {item.anchor_id}")
            hit_frame = anchor_frames[item.anchor_id]
            if not start_frame <= hit_frame < end_frame:
                raise ValueError(f"gallery item anchor falls outside shot range: {item.anchor_id}")
            compiled_gallery_items.append(
                CompiledGalleryItem(
                    asset_id=item.asset_id,
                    phrase=item.phrase,
                    anchor_id=item.anchor_id,
                    hit_frame=hit_frame,
                    onset_frame=hit_frame,
                )
            )
        render_shots.append(
            RenderShot(
                shot_id=shot.shot_id,
                scene_id=shot.scene_id,
                scene_kind=shot.scene_kind,
                track=shot.track,
                beat_ids=shot.beat_ids,
                template=shot.template,
                asset_bindings=shot.asset_bindings,
                claim_ids=shot.claim_ids,
                start_frame=start_frame,
                end_frame=end_frame,
                cues=cues,
                motion=shot.motion,
                transition_in=shot.transition_in.model_dump(mode="json"),
                long_hold_reason=shot.long_hold_reason,
                overlay_layout=shot.overlay_layout.model_dump(mode="json") if shot.overlay_layout else None,
                parameter_sequence=compiled_sequence,
                editor_flow_sequence=compiled_editor_flow,
                gallery_items=compiled_gallery_items,
            )
        )
        used_asset_ids.update(shot.asset_ids)

    _validate_claim_timing(narration, timing, render_shots)

    for event in _select_sfx_events(sfx_events, timing.fps, audio):
        audio_tracks.append(
            AudioTrack(
                kind="sfx",
                path=event.path,
                start_frame=event.start_frame,
                sync_frame=event.hit_frame,
                sync_point=event.sync_point,
                effective_sync_offset_ms=event.effective_sync_offset_ms,
                gain_db=event.gain_db,
                anchor_id=event.anchor_id,
                semantic_id=event.semantic_id,
                trim_start_ms=event.trim_start_ms,
                max_duration_ms=event.max_duration_ms,
                fade_in_ms=event.fade_in_ms,
                fade_out_ms=event.fade_out_ms,
            )
        )

    render_assets: list[RenderAsset] = []
    for asset_id in sorted(used_asset_ids):
        asset = asset_by_id[asset_id]
        if asset.media_type not in {"image", "video"} or not asset.width or not asset.height:
            raise ValueError(f"render asset is not valid visual media: {asset_id}")
        if asset.media_type == "video" and asset.role not in {"brand_ip_animation", "brand_ip_video"}:
            raise ValueError(f"video asset is not approved for deterministic rendering: {asset_id}")
        source_path = (repo_root / asset.path).resolve()
        render_assets.append(
            RenderAsset(
                asset_id=asset_id,
                path=source_path.as_posix(),
                sha256=asset.sha256,
                width=asset.width,
                height=asset.height,
                media_type=asset.media_type,
                fps=asset.metadata.get("fps"),
                frame_count=asset.metadata.get("frame_count"),
                duration_ms=asset.metadata.get("duration_ms"),
                accent_color=_accent_color(source_path) if asset.media_type == "image" else None,
            )
        )

    profile = get_profile(platform_profile)
    return RenderPlan(
        case_id=case_id,
        run_id=run_id,
        width=width,
        height=height,
        fps=timing.fps,
        frame_count=timing.duration_frames,
        preferred_min_sec=duration_policy.preferred_min_sec,
        preferred_max_sec=duration_policy.preferred_max_sec,
        hard_max_sec=duration_policy.hard_max_sec,
        platform_profile=platform_profile,
        assets=render_assets,
        shots=sorted(render_shots, key=lambda item: (item.track != "base", item.start_frame, item.shot_id)),
        subtitles=compile_subtitles(
            timing,
            gallery_items=[item for shot in visual.shots for item in shot.gallery_items],
        ),
        audio_tracks=audio_tracks,
        style={
            "render_backend": "remotion",
            "subtitle_font_size": 64,
            "subtitle_font_min": 58,
            "subtitle_font_max": 68,
            "subtitle_stroke": 4,
            "sfx_density": audio.sfx_density.model_dump(mode="json"),
            "safe_area": {
                "content": profile.content_safe.as_dict(),
                "critical": profile.critical_safe.as_dict(),
                "subtitle_top": profile.subtitle_top.as_dict(),
                "subtitle_lower": profile.subtitle_lower.as_dict(),
            },
        },
    )
