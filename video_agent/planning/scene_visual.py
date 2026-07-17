from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_agent.contracts import (
    ActionScenePlan,
    Asset,
    AssetCatalog,
    CueBinding,
    EditorFlowSequence,
    GalleryItem,
    Narration,
    ParameterFrameSequence,
    ShotPlan,
    TimingLock,
    TransitionIn,
    VisualPlan,
)
from video_agent.io import sha256_json

from .asset_match import motion_for as _motion_for

def _derived_for_request(catalog: AssetCatalog, request_id: str) -> Asset | None:
    return next((asset for asset in catalog.assets if asset.metadata.get("request_id") == request_id), None)


def _resolve_bindings(scene: object, catalog: AssetCatalog) -> dict[str, str]:
    bindings = dict(scene.asset_bindings)
    derived = [asset for request_id in scene.derivation_request_ids if (asset := _derived_for_request(catalog, request_id))]
    if not derived:
        return bindings
    replacement = derived[-1].asset_id
    if scene.scene_kind == "reference_input":
        bindings["primary"] = replacement
    elif scene.scene_kind == "result_to_flat_plan":
        bindings["output"] = replacement
    else:
        bindings["primary"] = replacement
    return bindings


def _repair_causal_binding(scene: object, bindings: dict[str, str], catalog: AssetCatalog) -> dict[str, str]:
    if scene.scene_kind in {"reference_to_result", "editor_before_after"} and bindings.get("input") == bindings.get("output"):
        candidate = next(
            (
                asset
                for asset in catalog.assets
                if asset.role == "reference_image"
                and asset.semantic_path == scene.feature_path
                and asset.metadata.get("purpose") == "action_scene"
            ),
            None,
        )
        if candidate:
            bindings["input"] = candidate.asset_id
    if scene.scene_kind == "result_to_flat_plan" and bindings.get("input") == bindings.get("output"):
        candidate = next(
            (
                asset
                for asset in catalog.assets
                if asset.role == "plane_result"
                and asset.semantic_path == scene.feature_path
                and asset.metadata.get("purpose") == "action_scene"
            ),
            None,
        )
        if candidate:
            bindings["output"] = candidate.asset_id
    return bindings


def _scene_config(repo_root: Path | None) -> dict[str, Any]:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "config" / "scene_effects.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid scene effects config: {path}") from exc
    return payload if isinstance(payload, dict) else {}


def _rule(config: dict[str, Any], kind: str, key: str, default: Any) -> Any:
    return config.get("scenes", {}).get(kind, {}).get(key, default)


def _transition(kind: str, first: bool, config: dict[str, Any]) -> TransitionIn:
    if first:
        return TransitionIn()
    configured = _rule(config, kind, "transition", None)
    if isinstance(configured, dict):
        return TransitionIn.model_validate(configured)
    if kind in {"result_gallery", "result_gallery_summary"}:
        return TransitionIn(kind="slide_left", duration_frames=8)
    return TransitionIn(kind="crossfade", duration_frames=6)


def _scene_sfx(kind: str, config: dict[str, Any]) -> str | None:
    configured = _rule(config, kind, "sfx", "__missing__")
    if configured != "__missing__":
        return str(configured) if configured else None
    if kind in {"feature_entry", "parameter_input", "reference_input"}:
        return "mouse_click"
    if kind in {"result_gallery", "result_gallery_summary", "result_detail"}:
        return "swish"
    if kind in {"reference_to_result", "result_to_flat_plan", "editor_before_after"}:
        return "transition_whoosh"
    return None


def _template(kind: str, config: dict[str, Any]) -> str:
    configured = _rule(config, kind, "template", None)
    if configured:
        return str(configured)
    if kind == "parameter_input":
        return "ui_params_focus"
    if kind in {"site_home", "feature_entry", "editor_workspace", "brand_closing"}:
        return "ui_feature_entry"
    if kind == "light_sweep_fallback":
        return "result_showcase"
    if kind in {"reference_to_result", "result_to_flat_plan", "editor_before_after"}:
        return "reference_to_result"
    return "result_showcase"


def _motion(kind: str, primary: Asset | None, binding_count: int, config: dict[str, Any]) -> str:
    configured = _rule(config, kind, "motion", None)
    if isinstance(configured, str):
        return configured
    if isinstance(configured, dict) and primary is not None:
        media_key = "animated" if primary.media_type == "video" else "static"
        selected = configured.get(media_key) or configured.get("default")
        if selected:
            return str(selected)
    if kind == "site_home":
        return str(primary.metadata.get("preferred_effect") or "spring_card_pop")
    if kind == "feature_entry":
        return "detail_push_in"
    if kind == "parameter_input":
        return "scale_in"
    if kind == "editor_workspace":
        return "fade_in"
    if kind == "brand_closing":
        return "light_sweep"
    if kind == "result_gallery":
        return "slide_gallery"
    if kind == "result_gallery_summary":
        return "card_stack" if binding_count > 1 else _motion_for(primary, "result_showcase")
    if kind in {"reference_to_result", "result_to_flat_plan", "editor_before_after"}:
        return "before_after"
    if kind == "light_sweep_fallback":
        return "light_sweep"
    if primary is None:
        raise ValueError(f"scene kind {kind} requires a primary asset")
    return _motion_for(primary, _template(kind, config))


def _parameter_sequence(
    primary: Asset,
    catalog: AssetCatalog,
    *,
    callout_reveal_frames: int,
) -> ParameterFrameSequence | None:
    sequence_ids = primary.metadata.get("sequence_asset_ids")
    if not isinstance(sequence_ids, dict) or set(sequence_ids) != {"base", "stage", "final"}:
        raw = next(
            (
                asset
                for asset in catalog.assets
                if asset.role == "feature_form_params"
                and asset.semantic_path == primary.semantic_path
                and asset.provenance.origin == "site_screenshot_library"
                and asset.asset_id != primary.asset_id
            ),
            None,
        )
        if raw is None or primary.provenance.origin == "site_screenshot_library":
            return None
        labels = [label for label in ("行业", "主题", "场景") if label in " ".join(primary.tags + [primary.filename])]
        return ParameterFrameSequence(
            sequence_id=f"sequence_{primary.asset_id}",
            base_asset_id=raw.asset_id,
            stage_asset_id=primary.asset_id,
            final_asset_id=primary.asset_id,
            required_field_labels=labels or ["行业", "主题", "场景"],
            callout_text="填写必填项",
            callout_reveal_frames=callout_reveal_frames,
        )
    labels = [str(item) for item in primary.metadata.get("required_field_labels", [])]
    callout = str(primary.metadata.get("callout_text") or "填写必填项")
    return ParameterFrameSequence(
        sequence_id=str(primary.metadata.get("sequence_id") or primary.asset_id),
        base_asset_id=str(sequence_ids["base"]),
        stage_asset_id=str(sequence_ids["stage"]),
        final_asset_id=str(sequence_ids["final"]),
        required_field_labels=labels or ["必填项"],
        callout_text=callout,
        callout_reveal_frames=callout_reveal_frames,
    )


def _anchor_for_phrase(timing: TimingLock, beat_ids: list[str], candidates: tuple[str, ...], fallback: str) -> str:
    anchors = [anchor for anchor in timing.phrase_anchors if anchor.beat_id in beat_ids]
    for candidate in candidates:
        exact = next((anchor for anchor in anchors if candidate == anchor.text), None)
        if exact:
            return exact.anchor_id
        containing = next((anchor for anchor in anchors if candidate in anchor.text or anchor.text in candidate), None)
        if containing:
            return containing.anchor_id
        for beat_id in beat_ids:
            tokens = [token for token in timing.tokens if token.beat_id == beat_id]
            joined = "".join(token.text for token in tokens)
            start = joined.find(candidate)
            if start < 0:
                continue
            cursor = 0
            for token in tokens:
                cursor += len(token.text)
                if cursor > start:
                    return token.token_id
    return fallback


def _editor_flow_sequence(scene: object, primary: Asset, timing: TimingLock) -> EditorFlowSequence | None:
    sequence_id = primary.metadata.get("editor_flow_sequence_id")
    sequence_assets = primary.metadata.get("editor_flow_asset_ids")
    rect = primary.metadata.get("focus_rect")
    if not sequence_id or not isinstance(sequence_assets, dict) or not isinstance(rect, dict):
        return None
    page_id = str(sequence_assets.get("page") or "")
    modal_id = str(sequence_assets.get("modal") or "")
    if not page_id or not modal_id:
        return None
    focus_anchor = _anchor_for_phrase(
        timing, scene.beat_ids, ("进入编辑页面", "编辑页面", "局部编辑", "编辑"), scene.start.anchor_id
    )
    modal_anchor = _anchor_for_phrase(
        timing, scene.beat_ids, ("随心调整修改", "调整修改", "局部编辑", "修改", "重绘"), focus_anchor
    )
    return EditorFlowSequence(
        sequence_id=str(sequence_id), page_asset_id=page_id, modal_asset_id=modal_id,
        focus_anchor_id=focus_anchor, modal_anchor_id=modal_anchor,
        focus_x=float(rect.get("x", 0.815)), focus_y=float(rect.get("y", 0.755)),
        focus_w=float(rect.get("w", 0.12)), focus_h=float(rect.get("h", 0.12)),
    )


def build_scene_visual_plan(
    case_id: str,
    narration: Narration,
    timing: TimingLock,
    scene_plan: ActionScenePlan,
    catalog: AssetCatalog,
    repo_root: Path | None = None,
) -> VisualPlan:
    del narration
    config = _scene_config(repo_root)
    assets = {asset.asset_id: asset for asset in catalog.assets}
    shots: list[ShotPlan] = []
    for scene in scene_plan.scenes:
        bindings = _resolve_bindings(scene, catalog)
        bindings = _repair_causal_binding(scene, bindings, catalog)
        unknown = sorted(set(bindings.values()) - set(assets))
        if unknown:
            raise ValueError(f"action scene references missing assets: {scene.scene_id}/{unknown}")
        primary = assets[next(iter(bindings.values()))] if bindings else None
        if primary is None and scene.scene_kind != "light_sweep_fallback":
            raise ValueError(f"action scene has no visual asset: {scene.scene_id}")
        template = _template(scene.scene_kind, config)
        parameter_sequence = (
            _parameter_sequence(
                primary,
                catalog,
                callout_reveal_frames=int(_rule(config, "parameter_input", "callout_reveal_frames", 10)),
            )
            if scene.scene_kind == "parameter_input" and primary is not None
            else None
        )
        editor_flow_sequence = (
            _editor_flow_sequence(scene, primary, timing)
            if scene.scene_kind == "editor_workspace" and primary is not None
            else None
        )
        if editor_flow_sequence:
            template = "editor_interaction"
        if parameter_sequence:
            bindings = {
                "base": parameter_sequence.base_asset_id,
                "stage": parameter_sequence.stage_asset_id,
                "final": parameter_sequence.final_asset_id,
            }
        if editor_flow_sequence:
            bindings = {"page": editor_flow_sequence.page_asset_id, "modal": editor_flow_sequence.modal_asset_id}
        cues: list[CueBinding] = []
        sfx = _scene_sfx(scene.scene_kind, config)
        if sfx:
            cues.append(CueBinding(action="visual.enter", anchor_id=scene.start.anchor_id, offset_frames=scene.start.offset_frames, sfx=sfx))
        if editor_flow_sequence:
            cues.append(CueBinding(action="editor.focus", anchor_id=editor_flow_sequence.focus_anchor_id))
            cues.append(CueBinding(action="editor.modal", anchor_id=editor_flow_sequence.modal_anchor_id, sfx="mouse_click"))
        gallery_items = [
            GalleryItem(asset_id=item.asset_id, phrase=item.phrase, anchor_id=item.anchor_id)
            for item in scene.gallery_items
        ]
        if gallery_items:
            cues.extend(CueBinding(action="visual.hit", anchor_id=item.anchor_id, sfx="swish") for item in gallery_items)
        shots.append(
            ShotPlan(
                shot_id=f"shot_{len(shots) + 1:03d}",
                scene_id=scene.scene_id,
                scene_kind=scene.scene_kind,
                track="base",
                beat_ids=scene.beat_ids,
                start=scene.start,
                end=scene.end,
                template=template,
                asset_bindings=bindings,
                cue_bindings=cues,
                energy="high" if scene.scene_kind in {"result_gallery", "result_gallery_summary"} else "medium",
                motion=_motion(scene.scene_kind, primary, len(bindings), config),
                transition_in=_transition(scene.scene_kind, not shots, config),
                long_hold_reason="reading" if scene.scene_kind in {"parameter_input", "editor_workspace"} else None,
                parameter_sequence=parameter_sequence,
                editor_flow_sequence=editor_flow_sequence,
                gallery_items=gallery_items,
            )
        )
    return VisualPlan(
        case_id=case_id,
        timing_lock_sha256=sha256_json(timing),
        action_scene_plan_sha256=sha256_json(scene_plan),
        shots=shots,
    )
