from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.ai.asset_selector import compact_asset_table, select_asset_candidates
from video_agent.contracts import ActionScene, ActionScenePlan, AssetCatalog, CaseConfig, Narration, TimeRef, TimingLock
from video_agent.io import load_json, sha256_json, write_json_atomic


def _asset_payload(catalog: AssetCatalog) -> dict[str, Any]:
    return compact_asset_table(catalog.assets)


def _timing_payload(timing: TimingLock) -> dict[str, Any]:
    return {
        "duration_frames": timing.duration_frames,
        "fps": timing.fps,
        "beat_span_fields": ["beat_id", "start_frame", "end_frame"],
        "beat_spans": [[span.beat_id, span.start_frame, span.end_frame] for span in timing.beat_spans],
    }


def _compact_text(text: str) -> str:
    return "".join(text.split())


def _token_anchor_for_phrase(timing: TimingLock, beat_ids: list[str], phrase: str) -> str:
    target = _compact_text(phrase)
    if not target:
        raise ValueError("AI scene start/gallery phrase must not be empty")
    for beat_id in beat_ids:
        tokens = [token for token in timing.tokens if token.beat_id == beat_id]
        joined = "".join(_compact_text(token.text) for token in tokens)
        start = joined.find(target)
        if start < 0:
            continue
        cursor = 0
        for token in tokens:
            size = len(_compact_text(token.text))
            if cursor + size > start:
                return token.token_id
            cursor += size
    raise ValueError(f"AI phrase does not occur verbatim in its beat text: {phrase}")


def _semantic_phrase_position(narration: Narration, beat_ids: list[str], phrase: str) -> int:
    compact_phrase = _compact_text(phrase)
    if not compact_phrase:
        raise ValueError("AI semantic phrase must not be empty")
    offset = 0
    allowed = set(beat_ids)
    for beat in narration.beats:
        compact_beat = _compact_text(beat.spoken_text)
        if beat.beat_id in allowed:
            local = compact_beat.find(compact_phrase)
            if local >= 0:
                return offset + local
        offset += len(compact_beat)
    raise ValueError(f"AI phrase does not occur verbatim in its declared beats: {phrase}")


def _validate_semantic_order(result: dict[str, Any], narration: Narration) -> None:
    scenes = result.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("AI action_scene JSON requires a non-empty scenes array")
    starts = [0]
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError("AI action_scene scenes must be JSON objects")
        beat_ids = scene.get("beat_ids")
        if not isinstance(beat_ids, list) or not beat_ids:
            raise ValueError(f"AI scene requires beat_ids: {scene.get('scene_id')}")
        if scene.get("narrative_role") not in {"opening", "body", "closing"}:
            raise ValueError(f"AI scene requires a valid narrative_role: {scene.get('scene_id')}")
        if not isinstance(scene.get("visual_purpose"), str) or not scene.get("visual_purpose"):
            raise ValueError(f"AI scene requires visual_purpose: {scene.get('scene_id')}")
        if index == 0:
            if scene.get("start_phrase") not in (None, ""):
                raise ValueError("first AI scene start_phrase must be null")
            continue
        phrase = scene.get("start_phrase")
        if not isinstance(phrase, str) or not phrase.strip():
            raise ValueError(f"AI scene requires an exact start_phrase: {scene.get('scene_id')}")
        position = _semantic_phrase_position(narration, beat_ids, phrase)
        if position <= starts[-1]:
            raise ValueError(
                f"scene start phrases must follow spoken order: {scene.get('scene_id')} starts at {phrase}"
            )
        starts.append(position)

    if len(scenes) == 1:
        if scenes[0].get("narrative_role") != "closing":
            raise ValueError("a single-scene plan must be marked closing")
    else:
        if scenes[0].get("narrative_role") != "opening":
            raise ValueError("the first AI scene must be marked opening")
        if scenes[-1].get("narrative_role") != "closing":
            raise ValueError("the final AI scene must be marked closing")
        invalid_body = [
            scene.get("scene_id")
            for scene in scenes[1:-1]
            if scene.get("narrative_role") != "body"
        ]
        if invalid_body:
            raise ValueError(f"middle AI scenes must be marked body: {invalid_body}")

    for index, scene in enumerate(scenes):
        scene_start = starts[index]
        scene_end = starts[index + 1] if index + 1 < len(starts) else None
        beat_ids = scene["beat_ids"]
        for item in scene.get("gallery_items", []):
            if not isinstance(item, dict) or not isinstance(item.get("phrase"), str):
                raise ValueError(f"AI gallery item requires an exact phrase: {scene.get('scene_id')}")
            item_position = _semantic_phrase_position(narration, beat_ids, item["phrase"])
            if item_position < scene_start or (scene_end is not None and item_position >= scene_end):
                boundary = scenes[index + 1].get("start_phrase") if index + 1 < len(scenes) else "timeline_end"
                raise ValueError(
                    f"gallery phrase is outside its scene spoken interval: scene={scene.get('scene_id')}, "
                    f"phrase={item['phrase']}, next_scene_start={boundary}. Split the gallery before the "
                    "next scene and create a new gallery/detail scene after any fallback."
                )


def _compile_semantic_result(
    result: dict[str, Any],
    case_id: str,
    narration: Narration,
    timing: TimingLock,
) -> ActionScenePlan:
    result = json.loads(json.dumps(result, ensure_ascii=False))
    raw_scenes = result.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("AI action_scene JSON requires a non-empty scenes array")
    beat_text = {beat.beat_id: beat.spoken_text for beat in narration.beats}
    scene_starts: list[TimeRef] = []
    for index, raw in enumerate(raw_scenes):
        if not isinstance(raw, dict):
            raise ValueError("AI action_scene scenes must be JSON objects")
        beat_ids = raw.get("beat_ids")
        if not isinstance(beat_ids, list) or not beat_ids or any(beat_id not in beat_text for beat_id in beat_ids):
            raise ValueError(f"AI scene has invalid beat_ids: {raw.get('scene_id')}")
        phrase = raw.pop("start_phrase", None)
        if index == 0:
            if phrase not in (None, ""):
                raise ValueError("first AI scene start_phrase must be null; it starts at timeline_start")
            scene_starts.append(TimeRef(anchor_id="timeline_start"))
        else:
            if not isinstance(phrase, str) or not phrase.strip():
                raise ValueError(f"AI scene requires an exact start_phrase: {raw.get('scene_id')}")
            if not any(_compact_text(phrase) in _compact_text(beat_text[beat_id]) for beat_id in beat_ids):
                raise ValueError(f"AI scene start_phrase is not in the declared beat: {phrase}")
            scene_starts.append(TimeRef(anchor_id=_token_anchor_for_phrase(timing, beat_ids, phrase)))

    scenes: list[ActionScene] = []
    for index, source in enumerate(raw_scenes):
        raw = dict(source)
        gallery = raw.get("gallery_items", [])
        if not isinstance(gallery, list):
            raise ValueError(f"AI scene gallery_items must be an array: {raw.get('scene_id')}")
        compiled_gallery = []
        for item in gallery:
            if not isinstance(item, dict) or not isinstance(item.get("phrase"), str):
                raise ValueError(f"AI gallery item requires asset_id and exact phrase: {raw.get('scene_id')}")
            compiled_gallery.append(
                {
                    "asset_id": item.get("asset_id"),
                    "phrase": item["phrase"].strip(),
                    "anchor_id": _token_anchor_for_phrase(timing, raw["beat_ids"], item["phrase"]),
                }
            )
        raw["start"] = scene_starts[index].model_dump(mode="json")
        raw["end"] = (
            scene_starts[index + 1].model_dump(mode="json")
            if index + 1 < len(scene_starts)
            else TimeRef(anchor_id="timeline_end").model_dump(mode="json")
        )
        raw["gallery_items"] = compiled_gallery
        raw.setdefault("asset_terms", [])
        raw.setdefault("feature_path", [])
        bindings = raw.setdefault("asset_bindings", {})
        if not isinstance(bindings, dict):
            raise ValueError(f"AI scene asset_bindings must be an object: {raw.get('scene_id')}")
        bindings = {key: value for key, value in bindings.items() if isinstance(value, str) and value}
        raw["asset_bindings"] = bindings
        for item_index, item in enumerate(compiled_gallery, start=1):
            if item["asset_id"] not in bindings.values():
                bindings[f"item_{item_index:03d}"] = item["asset_id"]
        raw.setdefault("derivation_request_ids", [])
        raw.setdefault("relationship_group_id", None)
        raw.setdefault("relationship_kind", None)
        raw.setdefault("fallback_policy", "exact")
        scenes.append(ActionScene.model_validate(raw))
    return ActionScenePlan(
        case_id=case_id,
        timing_lock_sha256=sha256_json(timing),
        scenes=scenes,
        derivation_requests=result.get("derivation_requests", []),
    )


def _anchor_frames(timing: TimingLock) -> dict[str, int]:
    frames = {"timeline_start": 0, "timeline_end": timing.duration_frames}
    frames.update({token.token_id: token.start_frame for token in timing.tokens})
    frames.update({anchor.anchor_id: anchor.hit_frame for anchor in timing.phrase_anchors})
    for span in timing.beat_spans:
        frames[f"beat_start:{span.beat_id}"] = span.start_frame
        frames[f"beat_end:{span.beat_id}"] = span.end_frame
    return frames


def _validate_plan(plan: ActionScenePlan, catalog: AssetCatalog, timing: TimingLock, narration: Narration) -> None:
    eligible_assets = {
        asset.asset_id: asset
        for asset in catalog.assets
        if asset.production_eligible and asset.quality.status != "rejected"
    }
    asset_ids = set(eligible_assets)
    beat_ids = {beat.beat_id for beat in narration.beats}
    anchors = _anchor_frames(timing)
    request_ids = {request.request_id for request in plan.derivation_requests}
    if len(plan.scenes) == 1:
        if plan.scenes[0].narrative_role != "closing":
            raise ValueError("a single-scene plan must end as closing")
    else:
        if plan.scenes[0].narrative_role != "opening":
            raise ValueError("AI scene plan must begin with narrative_role=opening")
        if plan.scenes[-1].narrative_role != "closing":
            raise ValueError("AI scene plan must end with narrative_role=closing")
        if any(scene.narrative_role != "body" for scene in plan.scenes[1:-1]):
            raise ValueError("all middle AI scenes must use narrative_role=body")
    unknown_assets: set[str] = set()
    previous_end = 0
    for index, scene in enumerate(plan.scenes):
        if set(scene.beat_ids) - beat_ids:
            raise ValueError(f"AI scene references unknown beat IDs: {scene.scene_id}")
        unknown_assets.update(set(scene.asset_bindings.values()) - asset_ids)
        bound_assets = [eligible_assets[asset_id] for asset_id in scene.asset_bindings.values() if asset_id in eligible_assets]
        if scene.visual_purpose in {"single_result_evidence", "multi_result_evidence"}:
            requests = [
                request
                for request in plan.derivation_requests
                if request.request_id in scene.derivation_request_ids
            ]
            if not any(asset.role == "result_image" for asset in bound_assets) and not any(
                request.output_role == "result_image" for request in requests
            ):
                raise ValueError(f"result evidence scene has no result image source: {scene.scene_id}")
        if scene.visual_purpose == "parameter_operation" and bound_assets and not any(
            asset.role == "feature_form_params" for asset in bound_assets
        ):
            raise ValueError(f"parameter operation scene has no parameter-page asset: {scene.scene_id}")
        for gallery_item in scene.gallery_items:
            unknown_assets.update({gallery_item.asset_id} - asset_ids)
        if scene.start.anchor_id not in anchors or scene.end.anchor_id not in anchors:
            raise ValueError(f"AI scene references unknown timing anchor: {scene.scene_id}")
        start = anchors[scene.start.anchor_id] + scene.start.offset_frames
        end = anchors[scene.end.anchor_id] + scene.end.offset_frames
        if start != previous_end:
            raise ValueError(
                f"AI scene timeline is not contiguous at {scene.scene_id}: expected frame {previous_end}, got {start}"
            )
        if end <= start:
            raise ValueError(f"AI scene has non-positive duration: {scene.scene_id}")
        for gallery_item in scene.gallery_items:
            if gallery_item.anchor_id not in anchors:
                raise ValueError(f"AI gallery item references unknown timing anchor: {gallery_item.anchor_id}")
            if not start <= anchors[gallery_item.anchor_id] < end:
                raise ValueError(f"AI gallery anchor falls outside scene: {scene.scene_id}/{gallery_item.anchor_id}")
        if index == 0 and scene.start.anchor_id != "timeline_start":
            raise ValueError("AI scene timeline must start at timeline_start")
        previous_end = end
    if previous_end != timing.duration_frames or plan.scenes[-1].end.anchor_id != "timeline_end":
        raise ValueError("AI scene timeline must end at timeline_end")
    for request in plan.derivation_requests:
        unknown_assets.update({request.source_asset_id, *request.related_asset_ids} - asset_ids)
        if request.scene_id and request.scene_id not in {scene.scene_id for scene in plan.scenes}:
            raise ValueError(f"AI derivation request references unknown scene: {request.request_id}")
        if request.derive_kind.value == "contextual_result_fill":
            source = eligible_assets.get(request.source_asset_id)
            if source and source.role != "result_image":
                raise ValueError(f"contextual_result_fill source must be a result_image: {request.request_id}")
            if request.output_role != "result_image":
                raise ValueError(f"contextual_result_fill output_role must be result_image: {request.request_id}")
            if not request.semantic_phrase or request.semantic_phrase not in request.instruction:
                raise ValueError(
                    f"contextual_result_fill instruction must name its exact semantic_phrase: {request.request_id}"
                )
            if not request.semantic_path or not any(
                request.semantic_phrase in part or part in request.semantic_phrase
                for part in request.semantic_path
            ):
                raise ValueError(
                    f"contextual_result_fill semantic_path must identify the missing phrase: {request.request_id}"
                )
            if request.target_orientation is None:
                raise ValueError(f"contextual_result_fill requires target_orientation: {request.request_id}")
    if unknown_assets:
        raise ValueError(f"AI scene plan references unknown asset IDs: {sorted(unknown_assets)}")
    dangling = {
        request_id
        for scene in plan.scenes
        for request_id in scene.derivation_request_ids
        if request_id not in request_ids
    }
    if dangling:
        raise ValueError(f"AI scene plan references unknown derivation request IDs: {sorted(dangling)}")


def _validate_gallery_recall(result: dict[str, Any], selection_report: dict[str, Any]) -> None:
    flash_result = selection_report.get("flash_result")
    phrase_candidates = flash_result.get("phrase_candidates", {}) if isinstance(flash_result, dict) else {}
    phrase_modes = flash_result.get("phrase_candidate_modes", {}) if isinstance(flash_result, dict) else {}
    if not isinstance(phrase_candidates, dict):
        return
    for scene in result.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        beat_ids = scene.get("beat_ids", [])
        for item in scene.get("gallery_items", []):
            if not isinstance(item, dict):
                continue
            phrase = item.get("phrase")
            asset_id = item.get("asset_id")
            allowed: set[str] | None = None
            for beat_id in beat_ids:
                beat_map = phrase_candidates.get(beat_id, {})
                mode_map = phrase_modes.get(beat_id, {}) if isinstance(phrase_modes, dict) else {}
                if isinstance(beat_map, dict) and phrase in beat_map and mode_map.get(phrase) == "result_item":
                    values = beat_map[phrase]
                    allowed = {str(value) for value in values} if isinstance(values, list) else set()
                    break
            if allowed is not None and asset_id not in allowed:
                raise ValueError(
                    f"gallery item violates Flash exact phrase candidates: phrase={phrase}, "
                    f"asset_id={asset_id}, allowed={sorted(allowed)}"
                )


def _validate_asset_gap_decisions(result: dict[str, Any], selection_report: dict[str, Any]) -> None:
    flash_result = selection_report.get("flash_result")
    phrase_candidates = flash_result.get("phrase_candidates", {}) if isinstance(flash_result, dict) else {}
    phrase_modes = flash_result.get("phrase_candidate_modes", {}) if isinstance(flash_result, dict) else {}
    all_empty = {
        (str(beat_id), str(phrase))
        for beat_id, phrase_map in phrase_candidates.items()
        if isinstance(phrase_map, dict)
        for phrase, candidates in phrase_map.items()
        if isinstance(candidates, list)
        and not candidates
    }
    required_missing = {
        (beat_id, phrase)
        for beat_id, phrase in all_empty
        if isinstance(phrase_modes.get(beat_id, {}), dict)
        and phrase_modes[beat_id].get(phrase) == "result_item"
    }
    decisions = result.get("asset_gap_decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("asset_gap_decisions must be an array")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("asset_gap_decisions entries must be JSON objects")
        key = (str(decision.get("beat_id", "")), str(decision.get("phrase", "")))
        if key in indexed:
            raise ValueError(f"duplicate asset gap decision: {key}")
        indexed[key] = decision
    if not required_missing <= set(indexed) or not set(indexed) <= all_empty:
        raise ValueError(
            f"asset_gap_decisions must resolve every empty result_item and may resolve empty supporting items; "
            f"missing={sorted(required_missing - set(indexed))}, unknown={sorted(set(indexed) - all_empty)}"
        )

    scenes = {str(scene.get("scene_id")): scene for scene in result.get("scenes", []) if isinstance(scene, dict)}
    requests = {
        str(request.get("request_id")): request
        for request in result.get("derivation_requests", [])
        if isinstance(request, dict)
    }
    for (beat_id, phrase), decision in indexed.items():
        action = decision.get("decision")
        reason = decision.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"asset gap decision requires a non-empty reason: {beat_id}/{phrase}")
        if action == "derive":
            if phrase_modes.get(beat_id, {}).get(phrase) != "result_item":
                raise ValueError(f"supporting asset gaps cannot use contextual result derivation: {beat_id}/{phrase}")
            request_id = decision.get("request_id")
            request = requests.get(str(request_id))
            if request is None:
                raise ValueError(f"derive gap decision references unknown request: {beat_id}/{phrase}/{request_id}")
            if request.get("derive_kind") != "contextual_result_fill":
                raise ValueError(f"derive gap decision must use contextual_result_fill: {beat_id}/{phrase}")
            if request.get("beat_id") != beat_id or request.get("semantic_phrase") != phrase:
                raise ValueError(f"derive request must preserve the exact missing beat and phrase: {beat_id}/{phrase}")
            scene = scenes.get(str(request.get("scene_id")))
            if scene is None or request_id not in scene.get("derivation_request_ids", []):
                raise ValueError(f"derived gap scene must reference its request: {beat_id}/{phrase}")
            if scene.get("start_phrase") != phrase:
                raise ValueError(f"derived gap scene must start at the missing phrase: {beat_id}/{phrase}")
        elif action == "light_sweep":
            matching = [
                scene
                for scene in scenes.values()
                if scene.get("scene_kind") == "light_sweep_fallback"
                and beat_id in scene.get("beat_ids", [])
                and (
                    scene.get("start_phrase") == phrase
                    or phrase in str(scene.get("semantic_phrase", ""))
                )
            ]
            if not matching:
                raise ValueError(f"light_sweep gap decision requires a matching fallback scene: {beat_id}/{phrase}")
        else:
            raise ValueError(f"asset gap decision must be derive or light_sweep: {beat_id}/{phrase}")


def plan_action_scenes(
    repo_root: Path,
    case: CaseConfig,
    narration: Narration,
    timing: TimingLock,
    catalog: AssetCatalog,
    selection_cache_path: Path | None = None,
) -> tuple[ActionScenePlan, list[dict[str, str]], dict[str, Any]]:
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "action_scene_planner.md")
    relationships_path = repo_root / "assets" / "relationships.json"
    relationships = load_json(relationships_path) if relationships_path.is_file() else {"relationships": []}
    candidates, selection_report, traces = select_asset_candidates(
        repo_root, case, narration, catalog, relationships, selection_cache_path
    )
    payload = {
        "case": {
            "case_id": case.case_id,
            "goal": case.goal,
            "feature_path": case.feature_path,
        },
        "narration": narration.model_dump(mode="json"),
        "timing": _timing_payload(timing),
        "assets": _asset_payload(candidates),
        "asset_selection_mode": selection_report.get("mode"),
        "asset_selection_fallback": selection_report.get("flash_failure"),
        "candidate_groups": selection_report.get("flash_result"),
        "relationships": {"relationships": selection_report["relationships"]},
    }
    user_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    semantic_cache_path = selection_cache_path.parent / "scene_semantic_response.json" if selection_cache_path else None
    semantic_input_sha256 = sha256_json(
        {"payload": payload, "prompt": prompt.sha256, "model": OpenAICompatibleTextClient(repo_root).model}
    )
    cached = load_json(semantic_cache_path) if semantic_cache_path and semantic_cache_path.is_file() else None
    if isinstance(cached, dict) and cached.get("input_sha256") == semantic_input_sha256:
        result = cached.get("result")
        if not isinstance(result, dict):
            raise ValueError("cached action_scene result is not a JSON object")
    else:
        result = OpenAICompatibleTextClient(repo_root).complete_json(
            prompt.text,
            user_json,
            "action_scene",
            max_tokens=4096,
            thinking=False,
        )
        if semantic_cache_path:
            write_json_atomic(
                semantic_cache_path,
                {"schema_version": 1, "input_sha256": semantic_input_sha256, "result": result},
            )
    client = OpenAICompatibleTextClient(repo_root)
    last_error: Exception | None = None
    for contract_attempt in range(3):
        try:
            _validate_semantic_order(result, narration)
            _validate_gallery_recall(result, selection_report)
            _validate_asset_gap_decisions(result, selection_report)
            plan = _compile_semantic_result(result, case.case_id, narration, timing)
            _validate_plan(plan, candidates, timing, narration)
            break
        except (ValueError, TypeError) as exc:
            last_error = exc
            if contract_attempt == 2:
                raise ValueError(f"action_scene JSON failed contract correction: {exc}") from exc
            correction_payload = {
                **payload,
                "previous_invalid_json": result,
                "validation_error": str(exc),
                "correction_instruction": (
                    "根据 validation_error 修正上一版，重新输出完整非空 JSON。不得编造素材 ID、"
                    "派生类型或空 source_asset_id；具体可视化功能缺素材时优先使用 contextual_result_fill，"
                    "只有抽象或不可可靠派生的语义才使用 light_sweep_fallback。"
                ),
            }
            result = client.complete_json(
                prompt.text + "\n这是契约纠错轮次，必须修正输入中的 validation_error 并返回完整 JSON。",
                json.dumps(correction_payload, ensure_ascii=False, separators=(",", ":")),
                "action_scene_correction",
                max_tokens=4096,
                thinking=False,
            )
            if semantic_cache_path:
                write_json_atomic(
                    semantic_cache_path,
                    {"schema_version": 1, "input_sha256": semantic_input_sha256, "result": result},
                )
    else:  # pragma: no cover - the loop either succeeds or raises
        raise ValueError(f"action_scene JSON correction failed: {last_error}")
    traces.append({"path": prompt.path.as_posix(), "sha256": prompt.sha256})
    return plan, traces, selection_report
