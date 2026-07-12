from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_agent.audio import merge_sfx_profile
from video_agent.contracts import (
    AssetCatalog,
    AudioConfig,
    AudioTrack,
    CompiledCue,
    DurationPolicy,
    RenderAsset,
    RenderPlan,
    RenderShot,
    TimingLock,
    VisualPlan,
)
from video_agent.compiler.subtitles import compile_subtitles


EFFECT_ALLOWLIST = {None, "cut", "crossfade", "fade_in", "fade_out", "scale_in", "scale_out", "page_slide", "perspective_push_in"}
TEXT_DENSE_TEMPLATES = {"ui_params_focus"}
TEXT_DENSE_EFFECT_ALLOWLIST = {None, "cut", "crossfade", "fade_in", "fade_out", "scale_in", "scale_out"}
BEAT_START_ANCHOR_PREFIX = "beat_start:"


@dataclass(frozen=True)
class _SfxEvent:
    semantic_id: str
    anchor_id: str
    hit_frame: int
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
    ranked = sorted(events, key=lambda item: (-item.priority, item.hit_frame, item.semantic_id))
    selected: list[_SfxEvent] = []
    for event in ranked:
        event_ms = event.hit_frame * 1000 / fps
        if any(abs(event_ms - chosen.hit_frame * 1000 / fps) < policy.min_gap_ms for chosen in selected):
            continue
        if any(
            chosen.semantic_id == event.semantic_id
            and abs(event_ms - chosen.hit_frame * 1000 / fps) < policy.repeat_cooldown_ms
            for chosen in selected
        ):
            continue
        events_in_window = sum(
            1 for chosen in selected if abs(event_ms - chosen.hit_frame * 1000 / fps) < policy.window_ms
        )
        if events_in_window >= policy.max_events_per_window:
            continue
        selected.append(event)
    return sorted(selected, key=lambda item: (item.hit_frame, item.semantic_id))


def compile_render_plan(
    case_id: str,
    run_id: str,
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
    if visual.case_id != case_id or timing.case_id != case_id:
        raise ValueError("case ids differ across timing and visual contracts")
    span_by_beat = {span.beat_id: span for span in timing.beat_spans}
    first_beat_id = min(timing.beat_spans, key=lambda item: item.start_frame).beat_id
    anchor_by_id = {anchor.anchor_id: anchor for anchor in timing.phrase_anchors}
    asset_by_id = {asset.asset_id: asset for asset in catalog.assets}
    render_shots: list[RenderShot] = []
    audio_tracks = [
        AudioTrack(
            kind="voice",
            path=str(Path(timing.audio_path).resolve()),
            start_frame=0,
            gain_db=audio.voice_gain_db,
        )
    ]
    sfx_profile = merge_sfx_profile(audio.sfx_profile, audio.sfx_overrides)
    sfx_events: list[_SfxEvent] = []
    if audio.bgm_path:
        bgm_path = (case_dir / audio.bgm_path).resolve()
        if not bgm_path.is_file():
            raise FileNotFoundError(f"BGM source is missing: {bgm_path}")
        audio_tracks.append(
            AudioTrack(
                kind="bgm",
                path=bgm_path.as_posix(),
                gain_db=audio.bgm_gain_db,
                loop=True,
                duck_under_voice=True,
            )
        )
    used_asset_ids: set[str] = set()
    for shot in visual.shots:
        if shot.beat_id not in span_by_beat:
            raise ValueError(f"shot references unknown beat: {shot.beat_id}")
        if shot.effect not in EFFECT_ALLOWLIST:
            raise ValueError(f"effect is not allowed in V3: {shot.effect}")
        if shot.template in TEXT_DENSE_TEMPLATES and shot.effect not in TEXT_DENSE_EFFECT_ALLOWLIST:
            raise ValueError(f"effect {shot.effect!r} distorts text-dense template {shot.template!r}")
        missing_assets = [asset_id for asset_id in shot.asset_ids if asset_id not in asset_by_id]
        if missing_assets:
            raise ValueError(f"shot references missing assets: {missing_assets}")
        unapproved = [
            asset_id
            for asset_id in shot.asset_ids
            if asset_by_id[asset_id].quality.status not in {"machine_checked", "vision_verified", "human_approved"}
        ]
        if unapproved:
            raise ValueError(f"shot references unapproved assets: {unapproved}")
        span = span_by_beat[shot.beat_id]
        cues: list[CompiledCue] = []
        for binding in shot.cue_bindings:
            anchor = anchor_by_id.get(binding.anchor_id)
            is_beat_start = binding.anchor_id == f"{BEAT_START_ANCHOR_PREFIX}{shot.beat_id}"
            if anchor is None and not is_beat_start:
                raise ValueError(f"shot references unknown phrase anchor: {binding.anchor_id}")
            if anchor is not None and anchor.beat_id != shot.beat_id:
                raise ValueError(f"cue anchor belongs to another beat: {binding.anchor_id}")
            anchor_id = binding.anchor_id if is_beat_start else anchor.anchor_id
            hit_frame = (0 if shot.beat_id == first_beat_id else span.start_frame) if is_beat_start else anchor.hit_frame
            cues.append(
                CompiledCue(
                    action=binding.action,
                    anchor_id=anchor_id,
                    hit_frame=hit_frame,
                    asset_anchor_id=binding.asset_anchor_id,
                )
            )
            if binding.sfx:
                source = sfx_profile.get(binding.sfx)
                if not source:
                    raise ValueError(f"SFX cue has no configured source: {binding.sfx}")
                sfx_path = _resolve_sfx_path(source.path, case_dir, repo_root)
                if not sfx_path.is_file():
                    raise FileNotFoundError(f"SFX source is missing: {sfx_path}")
                sfx_events.append(
                    _SfxEvent(
                        semantic_id=binding.sfx,
                        anchor_id=anchor_id,
                        hit_frame=hit_frame,
                        path=sfx_path.as_posix(),
                        gain_db=source.gain_db,
                        trim_start_ms=source.trim_start_ms,
                        max_duration_ms=source.max_duration_ms,
                        fade_in_ms=source.fade_in_ms,
                        fade_out_ms=source.fade_out_ms,
                        priority=source.priority,
                    )
                )
        render_shots.append(
            RenderShot(
                shot_id=shot.shot_id,
                beat_id=shot.beat_id,
                template=shot.template,
                asset_ids=shot.asset_ids,
                start_frame=span.start_frame,
                end_frame=span.end_frame,
                cues=cues,
                effect=shot.effect,
                long_hold_reason=shot.long_hold_reason,
            )
        )
        used_asset_ids.update(shot.asset_ids)

    for event in _select_sfx_events(sfx_events, timing.fps, audio):
        audio_tracks.append(
            AudioTrack(
                kind="sfx",
                path=event.path,
                start_frame=event.hit_frame,
                gain_db=event.gain_db,
                anchor_id=event.anchor_id,
                semantic_id=event.semantic_id,
                trim_start_ms=event.trim_start_ms,
                max_duration_ms=event.max_duration_ms,
                fade_in_ms=event.fade_in_ms,
                fade_out_ms=event.fade_out_ms,
            )
        )

    ordered_shots = sorted(render_shots, key=lambda item: item.start_frame)
    ordered_shots[0].start_frame = 0
    for previous, current in zip(ordered_shots, ordered_shots[1:]):
        previous.end_frame = current.start_frame
    ordered_shots[-1].end_frame = timing.duration_frames

    render_assets: list[RenderAsset] = []
    for asset_id in sorted(used_asset_ids):
        asset = asset_by_id[asset_id]
        if asset.media_type not in {"image", "video"} or not asset.width or not asset.height:
            raise ValueError(f"render asset is not valid visual media: {asset_id}")
        if asset.media_type == "video" and asset.role not in {"brand_ip_animation", "brand_ip_video"}:
            raise ValueError(f"video asset is not approved for deterministic rendering: {asset_id}")
        render_assets.append(
            RenderAsset(
                asset_id=asset_id,
                path=(repo_root / asset.path).resolve().as_posix(),
                sha256=asset.sha256,
                width=asset.width,
                height=asset.height,
                media_type=asset.media_type,
                fps=asset.metadata.get("fps"),
                frame_count=asset.metadata.get("frame_count"),
                duration_ms=asset.metadata.get("duration_ms"),
                anchors={anchor.anchor_id: anchor.rect.model_dump() for anchor in asset.visual_anchors},
                anchor_panels={
                    anchor.anchor_id: anchor.panel_rect.model_dump()
                    for anchor in asset.visual_anchors
                    if anchor.panel_rect is not None
                },
            )
        )

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
        shots=ordered_shots,
        subtitles=compile_subtitles(timing),
        audio_tracks=audio_tracks,
        style={
            "subtitle_font_size": 64,
            "subtitle_font_min": 58,
            "subtitle_font_max": 68,
            "subtitle_stroke": 4,
            "sfx_density": audio.sfx_density.model_dump(mode="json"),
        },
    )
