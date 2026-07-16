from __future__ import annotations

import hashlib
import unicodedata

from video_agent.contracts import (
    ActionScene,
    ActionScenePlan,
    Asset,
    AssetCatalog,
    DeriveKind,
    DerivedAssetRequest,
    Narration,
    SceneGalleryItem,
    TimeRef,
    TimingLock,
)
from video_agent.io import sha256_json

from .asset_match import (
    asset_matches_feature as _asset_matches_feature,
    enumerated_result_pairs as _enumerated_result_pairs,
    feature_result_match_score as _feature_result_match_score,
    feature_result_matches as _feature_result_matches,
    feature_scope as _feature_scope,
    role_assets as _role_assets,
)


BEAT_START = "beat_start:"
BEAT_END = "beat_end:"
TIMELINE_START = "timeline_start"
TIMELINE_END = "timeline_end"


def _normalize(text: str) -> str:
    compact = "".join(text.lower().split())
    return "".join(char for char in compact if not unicodedata.category(char).startswith("P"))


def _distinct_enumerated_pairs(pairs: list[tuple[Asset, object]]) -> list[tuple[Asset, object]]:
    """Collapse nested timing anchors that describe one spoken list item."""

    selected: list[tuple[Asset, object]] = []
    for asset, anchor in sorted(
        pairs,
        key=lambda item: (item[1].hit_frame, -len(_normalize(item[1].text))),
    ):
        term = _normalize(anchor.text)
        if any(
            anchor.hit_frame == existing.hit_frame
            and (term in _normalize(existing.text) or _normalize(existing.text) in term)
            for _, existing in selected
        ):
            continue
        selected.append((asset, anchor))
    return selected


def _token_anchor_for_phrase(timing: TimingLock, beat_id: str, phrase: str) -> str | None:
    tokens = [token for token in timing.tokens if token.beat_id == beat_id]
    normalized = _normalize(phrase)
    if not normalized:
        return None
    joined = "".join(_normalize(token.text) for token in tokens)
    start = joined.find(normalized)
    if start < 0:
        return None
    cursor = 0
    for token in tokens:
        size = len(_normalize(token.text))
        if cursor + size > start:
            return token.token_id
        cursor += size
    return None


def _phrase_anchor(timing: TimingLock, beat_id: str, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        anchor = next(
            (
                item
                for item in timing.phrase_anchors
                if item.beat_id == beat_id and _normalize(item.text) == _normalize(candidate)
            ),
            None,
        )
        if anchor:
            return anchor.anchor_id
        token_id = _token_anchor_for_phrase(timing, beat_id, candidate)
        if token_id:
            return token_id
        containing = next(
            (
                item
                for item in timing.phrase_anchors
                if item.beat_id == beat_id and _normalize(candidate) in _normalize(item.text)
            ),
            None,
        )
        if containing:
            return containing.anchor_id
    return None


def _semantic_phrase(beat_text: str, start_phrase: str | None, end_phrase: str | None = None) -> str:
    if start_phrase and start_phrase in beat_text:
        text = beat_text[beat_text.index(start_phrase) :]
    else:
        text = beat_text
    if end_phrase and end_phrase in text:
        text = text[: text.index(end_phrase)]
    return text.strip("，。！？：；, .!?:;") or beat_text


def _first_matching(assets: list[Asset], feature: str | None, *, filename_terms: tuple[str, ...] = ()) -> Asset | None:
    matching = [asset for asset in assets if not feature or _asset_matches_feature(asset, feature)]
    if filename_terms:
        preferred = [asset for asset in matching if any(term in asset.filename for term in filename_terms)]
        if preferred:
            return preferred[0]
    return matching[0] if matching else None


def _result_for_feature(roles: dict[str, list[Asset]], feature: str | None, used: set[str]) -> Asset | None:
    candidates = roles.get("result_image", [])
    if feature:
        candidates = sorted(
            (asset for asset in candidates if _feature_result_matches(feature, asset)),
            key=lambda asset: _feature_result_match_score(feature, asset),
        )
    fresh = [asset for asset in candidates if asset.asset_id not in used]
    return next(iter(fresh or candidates), None)


def _request(
    case_id: str,
    scene_id: str,
    kind: DeriveKind,
    source: Asset,
    phrase: str,
    feature_path: list[str],
    *,
    output_role: str,
    target_orientation: str = "portrait",
    related_asset_ids: list[str] | None = None,
) -> DerivedAssetRequest:
    digest = hashlib.sha256(f"{case_id}|{scene_id}|{kind.value}|{source.asset_id}|{phrase}".encode("utf-8")).hexdigest()[:12]
    return DerivedAssetRequest(
        request_id=f"derive_{digest}",
        source_asset_id=source.asset_id,
        related_asset_ids=related_asset_ids or [],
        derive_kind=kind,
        instruction=phrase,
        output_role=output_role,
        purpose="action_scene",
        semantic_path=list(feature_path),
        tags=[*feature_path, kind.value, scene_id],
        scene_id=scene_id,
        semantic_phrase=phrase,
        target_orientation=target_orientation,
        preserve=["主体内容", "主要文字", "品牌与配色"],
    )


def _scene_id(index: int) -> str:
    return f"scene_{index:03d}"


def _asset_orientation(asset: Asset) -> str:
    ratio = asset.width / max(1, asset.height)
    if ratio >= 1.2:
        return "landscape"
    if ratio <= 0.82:
        return "portrait"
    return "square"


def _visual_purpose(kind: str) -> str:
    if kind == "site_home":
        return "product_overview"
    if kind == "feature_entry":
        return "feature_navigation"
    if kind == "parameter_input":
        return "parameter_operation"
    if kind == "result_detail":
        return "single_result_evidence"
    if kind in {"result_gallery", "result_gallery_summary"}:
        return "multi_result_evidence"
    if kind in {"reference_input", "reference_to_result", "result_to_flat_plan"}:
        return "causal_evidence"
    if kind in {"editor_workspace", "editor_before_after"}:
        return "editor_operation"
    if kind == "brand_closing":
        return "brand_close"
    return "abstract_bridge"


def build_action_scene_plan(
    case_id: str,
    narration: Narration,
    timing: TimingLock,
    catalog: AssetCatalog,
) -> ActionScenePlan:
    roles = _role_assets(catalog)
    anchors_by_beat: dict[str, list[object]] = {}
    for anchor in timing.phrase_anchors:
        anchors_by_beat.setdefault(anchor.beat_id, []).append(anchor)
    scenes: list[ActionScene] = []
    requests: list[DerivedAssetRequest] = []
    used_results: set[str] = set()
    last_result: Asset | None = None
    assets_by_id = {asset.asset_id: asset for asset in catalog.assets}

    def add_scene(
        *,
        kind: str,
        beat_id: str,
        phrase: str,
        start: TimeRef,
        end: TimeRef,
        feature: str | None,
        bindings: dict[str, str],
        gallery: list[SceneGalleryItem] | None = None,
        derivations: list[DerivedAssetRequest] | None = None,
        relationship_kind: str | None = None,
        fallback_policy: str = "exact",
    ) -> None:
        scene_requests = derivations or []
        requests.extend(scene_requests)
        feature_path = ["文生图", feature] if feature else []
        scenes.append(
            ActionScene(
                scene_id=_scene_id(len(scenes) + 1),
                scene_kind=kind,
                narrative_role="body",
                visual_purpose=_visual_purpose(kind),
                beat_ids=[beat_id],
                semantic_phrase=phrase,
                start=start,
                end=end,
                feature_path=feature_path,
                asset_terms=[feature] if feature else [],
                asset_bindings=bindings,
                gallery_items=gallery or [],
                derivation_request_ids=[item.request_id for item in scene_requests],
                relationship_group_id=(
                    f"flow_{hashlib.sha256('|'.join(feature_path).encode('utf-8')).hexdigest()[:10]}"
                    if relationship_kind and feature_path
                    else None
                ),
                relationship_kind=relationship_kind,
                fallback_policy=fallback_policy,
            )
        )

    def fallback_asset() -> Asset:
        if scenes:
            bindings = scenes[-1].asset_bindings
            asset_id = bindings.get("output") or bindings.get("primary")
            if not asset_id and scenes[-1].gallery_items:
                asset_id = scenes[-1].gallery_items[-1].asset_id
            if not asset_id and bindings:
                asset_id = next(reversed(bindings.values()))
            if asset_id and asset_id in assets_by_id:
                return assets_by_id[asset_id]
        candidates = roles.get("site_home", []) + roles.get("result_image", [])
        if candidates:
            return candidates[0]
        raise ValueError("light-sweep fallback requires at least one non-brand visual asset")

    def add_fallback(*, beat_id: str, phrase: str, start: TimeRef, end: TimeRef, feature: str | None) -> None:
        asset = fallback_asset()
        add_scene(
            kind="light_sweep_fallback",
            beat_id=beat_id,
            phrase=phrase,
            start=start,
            end=end,
            feature=feature,
            bindings={"primary": asset.asset_id},
            fallback_policy="light_sweep",
        )

    active_feature: str | None = None
    for beat_index, beat in enumerate(narration.beats):
        beat_id = beat.beat_id
        is_first = beat_index == 0
        is_last = beat_index == len(narration.beats) - 1
        beat_start = TimeRef(anchor_id=TIMELINE_START if is_first else f"{BEAT_START}{beat_id}")
        beat_end = TimeRef(anchor_id=TIMELINE_END if is_last else f"{BEAT_END}{beat_id}")
        feature = _feature_scope(beat.spoken_text, beat.asset_slots, roles)
        intent = _normalize(" ".join([beat.spoken_text, *beat.asset_slots]))
        beat_anchors = sorted(anchors_by_beat.get(beat_id, []), key=lambda item: item.hit_frame)
        enumerated = _distinct_enumerated_pairs(
            _enumerated_result_pairs(beat_anchors, roles, used_results)
        )
        is_gallery = beat.visual_strategy == "enumerated_results" or len(enumerated) >= 2
        if not is_gallery:
            if feature:
                active_feature = feature
            elif active_feature:
                feature = active_feature

        if is_gallery:
            explicit = [pair for pair in enumerated if pair[1].text in beat.hit_phrases] or enumerated
            if len(explicit) < 2:
                raise ValueError(f"spoken result gallery has too few matching materials: {beat_id}")
            bindings = {f"item_{index + 1:03d}": asset.asset_id for index, (asset, _) in enumerate(explicit)}
            gallery = [
                SceneGalleryItem(asset_id=asset.asset_id, phrase=anchor.text, anchor_id=anchor.anchor_id)
                for asset, anchor in explicit
            ]
            used_results.update(asset.asset_id for asset, _ in explicit)
            last_result = explicit[-1][0]
            summary_anchor = _phrase_anchor(timing, beat_id, ("等各类设计", "各类设计", "它都能一键生成", "一键生成"))
            gallery_end = TimeRef(anchor_id=summary_anchor) if summary_anchor else beat_end
            add_scene(
                kind="result_gallery",
                beat_id=beat_id,
                phrase="、".join(anchor.text for _, anchor in explicit),
                start=beat_start,
                end=gallery_end,
                feature=None,
                bindings=bindings,
                gallery=gallery,
            )
            if summary_anchor:
                fresh = [asset for asset in roles.get("result_image", []) if asset.asset_id not in used_results]
                # CardStack has four readable simultaneous positions. This is
                # an effect capacity, not a global asset-count limit.
                summary_assets = fresh[:4] or [asset for asset, _ in explicit]
                add_scene(
                    kind="result_gallery_summary",
                    beat_id=beat_id,
                    phrase=_semantic_phrase(beat.spoken_text, "等各类设计"),
                    start=TimeRef(anchor_id=summary_anchor),
                    end=beat_end,
                    feature=None,
                    bindings={f"item_{index + 1:03d}": asset.asset_id for index, asset in enumerate(summary_assets)},
                )
            continue

        if is_first and roles.get("site_home") and not any(word in intent for word in ("参数", "编辑", "参考图", "效果图")):
            add_scene(
                kind="site_home",
                beat_id=beat_id,
                phrase=beat.spoken_text,
                start=beat_start,
                end=beat_end,
                feature=None,
                bindings={"primary": roles["site_home"][0].asset_id},
            )
            continue

        if any(word in intent for word in ("编辑页面", "局部编辑", "随心调整", "调整修改", "细节不满意")):
            editor = _first_matching(roles.get("editor_workspace", []), feature)
            source_result = last_result if last_result and (not feature or _asset_matches_feature(last_result, feature)) else _result_for_feature(roles, feature, used_results)
            fixed_editor = next(
                (
                    asset
                    for asset in roles.get("editor_workspace", [])
                    if source_result
                    and asset.metadata.get("editor_flow_sequence_id")
                    and asset.metadata.get("source_artwork_sha256") == source_result.sha256
                ),
                None,
            )
            if fixed_editor:
                sequence_assets = fixed_editor.metadata.get("editor_flow_asset_ids", {})
                modal_id = sequence_assets.get("modal") if isinstance(sequence_assets, dict) else None
                if modal_id in assets_by_id:
                    add_scene(
                        kind="editor_workspace",
                        beat_id=beat_id,
                        phrase=beat.spoken_text,
                        start=beat_start,
                        end=beat_end,
                        feature=feature,
                        bindings={"page": fixed_editor.asset_id, "modal": str(modal_id)},
                        relationship_kind="result_to_editor_flow",
                    )
                    continue
            if editor and source_result:
                edit_anchor = _phrase_anchor(timing, beat_id, ("随心调整修改", "调整修改", "随心调整", "修改"))
                composite_scene_id = _scene_id(len(scenes) + 1)
                composite = _request(
                    case_id,
                    composite_scene_id,
                    DeriveKind.RESULT_TO_EDITOR_COMPOSITE,
                    source_result,
                    "把上一张结果图完整载入真实编辑页面，保持编辑器 UI 和结果图内容不变",
                    ["文生图", feature] if feature else [],
                    output_role="editor_workspace",
                    related_asset_ids=[editor.asset_id],
                )
                add_scene(
                    kind="editor_workspace",
                    beat_id=beat_id,
                    phrase=_semantic_phrase(beat.spoken_text, None, "调整" if edit_anchor else None),
                    start=beat_start,
                    end=TimeRef(anchor_id=edit_anchor) if edit_anchor else beat_end,
                    feature=feature,
                    bindings={"primary": source_result.asset_id},
                    derivations=[composite],
                    relationship_kind="result_to_editor",
                )
                if edit_anchor:
                    edit_scene_id = _scene_id(len(scenes) + 1)
                    edited = _request(
                        case_id,
                        edit_scene_id,
                        DeriveKind.RESULT_TO_EDIT_STATE,
                        source_result,
                        beat.spoken_text,
                        ["文生图", feature] if feature else [],
                        output_role="result_image",
                        target_orientation=_asset_orientation(source_result),
                    )
                    add_scene(
                        kind="editor_before_after",
                        beat_id=beat_id,
                        phrase=_semantic_phrase(beat.spoken_text, "调整"),
                        start=TimeRef(anchor_id=edit_anchor),
                        end=beat_end,
                        feature=feature,
                        bindings={"input": source_result.asset_id, "output": source_result.asset_id},
                        derivations=[edited],
                        relationship_kind="result_to_edit_state",
                    )
            else:
                add_fallback(beat_id=beat_id, phrase=beat.spoken_text, start=beat_start, end=beat_end, feature=feature)
            continue

        if any(word in intent for word in ("实景功能", "场景照片", "参考图", "现场照片", "平面图")):
            upload_anchor = _phrase_anchor(timing, beat_id, ("上传你的场景照片参考图", "上传", "场景照片参考图"))
            generate_anchor = _phrase_anchor(timing, beat_id, ("系统就能", "原有场景基础上生成", "基础上生成"))
            flat_anchor = _phrase_anchor(timing, beat_id, ("同时还能一键导出平面图", "同时还能", "导出平面图", "平面图"))
            reference = _first_matching(roles.get("reference_image", []), feature, filename_terms=("实景", "现场", "参考图"))
            result = last_result if last_result and (not feature or _asset_matches_feature(last_result, feature)) else _result_for_feature(roles, feature, used_results)
            if result:
                used_results.add(result.asset_id)
            if not reference and result:
                sid = _scene_id(len(scenes) + 1)
                request = _request(case_id, sid, DeriveKind.RESULT_TO_REFERENCE_MOCK, result, "生成对应的模拟实景参考图", ["文生图", feature] if feature else [], output_role="reference_image")
                reference = result
                derivations = [request]
            else:
                derivations = []
            if not reference:
                add_fallback(beat_id=beat_id, phrase=beat.spoken_text, start=beat_start, end=beat_end, feature=feature)
                continue
            if upload_anchor:
                add_fallback(
                    beat_id=beat_id,
                    phrase=_semantic_phrase(beat.spoken_text, None, "上传"),
                    start=beat_start,
                    end=TimeRef(anchor_id=upload_anchor),
                    feature=feature,
                )
            reference_end = TimeRef(anchor_id=generate_anchor) if generate_anchor else beat_end
            add_scene(
                kind="reference_input",
                beat_id=beat_id,
                phrase=_semantic_phrase(beat.spoken_text, "上传" if "上传" in beat.spoken_text else None, "系统" if "系统" in beat.spoken_text else None),
                start=TimeRef(anchor_id=upload_anchor) if upload_anchor else beat_start,
                end=reference_end,
                feature=feature,
                bindings={"primary": reference.asset_id},
                derivations=derivations,
                fallback_policy="derive_or_fallback" if derivations else "exact",
            )
            if generate_anchor and result:
                add_scene(
                    kind="reference_to_result",
                    beat_id=beat_id,
                    phrase=_semantic_phrase(beat.spoken_text, "系统", "同时" if "同时" in beat.spoken_text else "平面图"),
                    start=TimeRef(anchor_id=generate_anchor),
                    end=TimeRef(anchor_id=flat_anchor) if flat_anchor else beat_end,
                    feature=feature,
                    bindings={"input": reference.asset_id, "output": result.asset_id},
                    relationship_kind="reference_to_result",
                )
            if flat_anchor and result:
                flat = _first_matching(roles.get("plane_result", []) + roles.get("reference_image", []), feature, filename_terms=("平面图", "平面"))
                flat_requests: list[DerivedAssetRequest] = []
                if not flat:
                    sid = _scene_id(len(scenes) + 1)
                    flat_requests = [_request(case_id, sid, DeriveKind.RESULT_TO_FLAT_PLAN, result, "基于结果图生成对应平面图", ["文生图", feature] if feature else [], output_role="plane_result")]
                    flat = result
                add_scene(
                    kind="result_to_flat_plan",
                    beat_id=beat_id,
                    phrase=_semantic_phrase(beat.spoken_text, "导出平面图" if "导出平面图" in beat.spoken_text else "平面图"),
                    start=TimeRef(anchor_id=flat_anchor),
                    end=beat_end,
                    feature=feature,
                    bindings={"input": result.asset_id, "output": flat.asset_id},
                    derivations=flat_requests,
                    relationship_kind="result_to_flat_plan",
                    fallback_policy="derive_or_fallback" if flat_requests else "exact",
                )
            continue

        if any(word in intent for word in ("举例", "功能入口", "点击进入", "进入文生图")):
            entry = _first_matching(roles.get("feature_entry", []), feature)
            if not entry:
                raise ValueError(f"missing feature entry material for {feature or beat_id}")
            add_scene(kind="feature_entry", beat_id=beat_id, phrase=beat.spoken_text, start=beat_start, end=beat_end, feature=feature, bindings={"primary": entry.asset_id})
            continue

        parameter_intent = any(word in intent for word in ("所属行业", "参数", "主题", "场景", "填写", "必填项"))
        result_anchor = _phrase_anchor(timing, beat_id, ("即刻出", "效果图", "一键生成")) if parameter_intent else None
        if parameter_intent:
            params = _first_matching(roles.get("feature_form_params", []), feature)
            if not params:
                raise ValueError(f"missing parameter material for {feature or beat_id}")
            add_scene(
                kind="parameter_input",
                beat_id=beat_id,
                phrase=_semantic_phrase(beat.spoken_text, None, "即刻" if "即刻" in beat.spoken_text else "效果图"),
                start=beat_start,
                end=TimeRef(anchor_id=result_anchor) if result_anchor else beat_end,
                feature=feature,
                bindings={"primary": params.asset_id},
            )
            if result_anchor:
                result = _result_for_feature(roles, feature, used_results)
                if result:
                    used_results.add(result.asset_id)
                    last_result = result
                    add_scene(
                        kind="result_detail",
                        beat_id=beat_id,
                        phrase=_semantic_phrase(beat.spoken_text, "即刻" if "即刻" in beat.spoken_text else "效果图"),
                        start=TimeRef(anchor_id=result_anchor),
                        end=beat_end,
                        feature=feature,
                        bindings={"primary": result.asset_id},
                    )
            continue

        if any(word in intent for word in ("功能齐全", "零基础", "轻松上手", "收藏", "关注")):
            add_fallback(beat_id=beat_id, phrase=beat.spoken_text, start=beat_start, end=beat_end, feature=feature)
            continue

        result = _result_for_feature(roles, feature, used_results)
        if result:
            used_results.add(result.asset_id)
            last_result = result
            add_scene(kind="result_detail", beat_id=beat_id, phrase=beat.spoken_text, start=beat_start, end=beat_end, feature=feature, bindings={"primary": result.asset_id})
            continue
        add_fallback(beat_id=beat_id, phrase=beat.spoken_text, start=beat_start, end=beat_end, feature=feature)

    # A spoken pause keeps the preceding visual alive.  Scene boundaries are
    # therefore contiguous even when TTS inserts silence between beats.
    contiguous: list[ActionScene] = []
    for index, scene in enumerate(scenes):
        end = scenes[index + 1].start if index + 1 < len(scenes) else TimeRef(anchor_id=TIMELINE_END)
        role = "closing" if index == len(scenes) - 1 else "opening" if index == 0 else "body"
        contiguous.append(scene.model_copy(update={"end": end, "narrative_role": role}))

    return ActionScenePlan(
        case_id=case_id,
        timing_lock_sha256=sha256_json(timing),
        scenes=contiguous,
        derivation_requests=requests,
    )
