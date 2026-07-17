from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_agent.ai.asset_index import AIAssetIndex
from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.contracts import Asset, AssetCatalog, CaseConfig, Narration
from video_agent.io import load_json, sha256_json, write_json_atomic
from video_agent.progress import get_logger


logger = get_logger()


def compact_asset_table(assets: list[Asset], asset_index: AIAssetIndex) -> dict[str, Any]:
    return asset_index.compact_table(assets)


def _relationship_asset_ids(relationship: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for key, value in relationship.items()
        if key.endswith("_asset_id") and isinstance(value, str) and value
    }


def _relationship_closure(
    selected: set[str],
    relationships: list[dict[str, Any]],
    valid_ids: set[str],
) -> tuple[set[str], list[dict[str, Any]]]:
    expanded = set(selected)
    included: list[dict[str, Any]] = []
    changed = True
    while changed:
        changed = False
        for relationship in relationships:
            relation_ids = _relationship_asset_ids(relationship) & valid_ids
            if relation_ids & expanded and relationship not in included:
                included.append(relationship)
                before = len(expanded)
                expanded.update(relation_ids)
                changed = changed or len(expanded) != before
    return expanded, included


def _validate_flash_result(
    result: dict[str, Any], narration: Narration, asset_index: AIAssetIndex
) -> set[str]:
    valid_refs = asset_index.refs
    beat_candidates = result.get("beat_candidates")
    if not isinstance(beat_candidates, dict) or not beat_candidates:
        raise ValueError("Flash asset selector must return a non-empty beat_candidates object")
    beat_ids = {beat.beat_id for beat in narration.beats}
    if set(beat_candidates) != beat_ids:
        raise ValueError(
            f"Flash asset selector must return every beat exactly once; missing={sorted(beat_ids - set(beat_candidates))}, "
            f"unknown={sorted(set(beat_candidates) - beat_ids)}"
        )
    selected: set[str] = set()
    for beat_id, candidates in beat_candidates.items():
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"Flash asset selector must return at least one candidate for {beat_id}")
        selected.update(str(asset_id) for asset_id in candidates)
    phrase_candidates = result.get("phrase_candidates", {})
    if not isinstance(phrase_candidates, dict) or not set(phrase_candidates) <= beat_ids:
        raise ValueError("Flash asset selector phrase_candidates must be keyed by known beat IDs")
    phrase_modes = result.get("phrase_candidate_modes", {})
    if not isinstance(phrase_modes, dict) or set(phrase_modes) != set(phrase_candidates):
        raise ValueError("Flash phrase_candidate_modes must cover the same beats as phrase_candidates")
    for beat_id, phrase_map in phrase_candidates.items():
        if not isinstance(phrase_map, dict):
            raise ValueError(f"Flash phrase_candidates must be an object for {beat_id}")
        mode_map = phrase_modes.get(beat_id)
        if not isinstance(mode_map, dict) or set(mode_map) != set(phrase_map):
            raise ValueError(f"Flash phrase_candidate_modes must cover every phrase for {beat_id}")
        for phrase, candidates in phrase_map.items():
            if not isinstance(phrase, str) or not isinstance(candidates, list):
                raise ValueError(f"Flash phrase candidate entry is invalid for {beat_id}")
            mode = mode_map.get(phrase)
            if mode not in {"result_item", "supporting"}:
                raise ValueError(f"Flash phrase candidate mode is invalid for {beat_id}/{phrase}: {mode}")
            selected.update(str(asset_id) for asset_id in candidates)
            invalid_results = [
                str(asset_id)
                for asset_id in candidates
                if mode == "result_item"
                and str(asset_id) in valid_refs
                and (
                    asset_index.asset(str(asset_id)).role != "result_image"
                    or not any(
                        semantic_part in phrase or phrase in semantic_part
                        for semantic_part in asset_index.asset(str(asset_id)).semantic_path
                    )
                )
            ]
            if invalid_results:
                raise ValueError(
                    f"Flash exact phrase candidates must be result_image assets whose semantic_path contains "
                    f"the exact phrase: beat={beat_id}, phrase={phrase}, invalid={invalid_results}. "
                    "Return exact result images or an empty array."
                )
    unknown = selected - valid_refs
    if unknown:
        raise ValueError(f"Flash asset selector returned unknown asset_ref values: {sorted(unknown)}")
    return selected


def _repair_exact_phrase_candidates(
    result: dict[str, Any], narration: Narration, asset_index: AIAssetIndex
) -> dict[str, Any]:
    """Repair only catalog-provable exact result matches; never infer near synonyms."""

    repaired = json.loads(json.dumps(result, ensure_ascii=False))
    phrase_candidates = repaired.get("phrase_candidates")
    phrase_modes = repaired.get("phrase_candidate_modes")
    beat_candidates = repaired.get("beat_candidates")
    if not isinstance(phrase_candidates, dict) or not isinstance(phrase_modes, dict):
        return repaired
    beat_text = {beat.beat_id: "".join(beat.spoken_text.split()) for beat in narration.beats}

    # The model may return a valid verbatim phrase under the wrong beat. Beat
    # ownership is deterministic, so repair it before any candidate checks.
    for source_beat_id, phrase_map in list(phrase_candidates.items()):
        if not isinstance(phrase_map, dict):
            continue
        source_modes = phrase_modes.get(source_beat_id)
        if not isinstance(source_modes, dict):
            continue
        for phrase, candidates in list(phrase_map.items()):
            if not isinstance(phrase, str):
                continue
            compact_phrase = "".join(phrase.split())
            matching_beats = [
                beat_id for beat_id, spoken_text in beat_text.items() if compact_phrase and compact_phrase in spoken_text
            ]
            if source_beat_id in matching_beats or len(matching_beats) != 1:
                continue
            target_beat_id = matching_beats[0]
            target_phrases = phrase_candidates.setdefault(target_beat_id, {})
            target_modes = phrase_modes.setdefault(target_beat_id, {})
            if not isinstance(target_phrases, dict) or not isinstance(target_modes, dict):
                continue
            existing = target_phrases.get(phrase, [])
            merged = list(
                dict.fromkeys(
                    [
                        *(existing if isinstance(existing, list) else []),
                        *(candidates if isinstance(candidates, list) else []),
                    ]
                )
            )
            target_phrases[phrase] = merged
            target_modes[phrase] = source_modes.get(phrase)
            del phrase_map[phrase]
            source_modes.pop(phrase, None)
            if isinstance(beat_candidates, dict) and isinstance(beat_candidates.get(target_beat_id), list):
                beat_candidates[target_beat_id] = list(
                    dict.fromkeys([*beat_candidates[target_beat_id], *merged])
                )
            logger.info(
                "[素材粗筛] 程序修正短语所属 beat phrase=%s from=%s to=%s",
                phrase,
                source_beat_id,
                target_beat_id,
            )

    known_beats = set(beat_text)
    for beat_id, phrase_map in phrase_candidates.items():
        if beat_id not in known_beats or not isinstance(phrase_map, dict):
            continue
        mode_map = phrase_modes.get(beat_id)
        if not isinstance(mode_map, dict):
            continue
        for phrase, candidates in phrase_map.items():
            if mode_map.get(phrase) != "result_item" or not isinstance(phrase, str):
                continue
            if not isinstance(candidates, list):
                continue
            exact_refs = [
                asset_ref
                for asset_ref, asset in asset_index.assets_by_ref.items()
                if asset.role == "result_image"
                and any(
                    semantic_part in phrase or phrase in semantic_part
                    for semantic_part in asset.semantic_path
                )
            ]
            valid_returned = [
                str(asset_ref)
                for asset_ref in candidates
                if str(asset_ref) in exact_refs
            ]
            canonical = list(dict.fromkeys([*valid_returned, *exact_refs]))
            if canonical != candidates:
                logger.info(
                    "[素材粗筛] 程序修正精确短语候选 beat=%s phrase=%s count=%d",
                    beat_id,
                    phrase,
                    len(canonical),
                )
                phrase_map[phrase] = canonical
            if isinstance(beat_candidates, dict) and isinstance(beat_candidates.get(beat_id), list):
                beat_candidates[beat_id] = list(
                    dict.fromkeys([*beat_candidates[beat_id], *canonical])
                )
    return repaired


def select_asset_candidates(
    repo_root: Path,
    case: CaseConfig,
    narration: Narration,
    catalog: AssetCatalog,
    relationships_payload: dict[str, Any],
    cache_path: Path | None = None,
) -> tuple[AssetCatalog, dict[str, Any], list[dict[str, str]], AIAssetIndex]:
    eligible = [
        asset
        for asset in catalog.assets
        if asset.production_eligible
        and asset.quality.status != "rejected"
        and asset.role != "outro"
        and asset.media_type != "audio"
    ]
    asset_index = AIAssetIndex.build(eligible)
    if cache_path:
        write_json_atomic(cache_path.parent / "ai_asset_index.json", asset_index.manifest())
    by_id = {asset.asset_id: asset for asset in eligible}
    valid_ids = set(by_id)
    required_ids = {asset_id for asset_id in case.selected_asset_ids if asset_id in valid_ids}
    relationships = [
        item for item in relationships_payload.get("relationships", []) if isinstance(item, dict)
    ]
    traces: list[dict[str, str]] = []

    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "asset_coarse_selector.md")
    client = OpenAICompatibleTextClient(repo_root)
    input_sha256 = sha256_json(
        {
            "case": case.model_dump(mode="json"),
            "narration": narration.model_dump(mode="json"),
            "catalog": catalog.source_catalog_sha256,
            "prompt": prompt.sha256,
            "model": client.coarse_model,
            "asset_index": asset_index.manifest()["index_sha256"],
            "selector_contract_version": 6,
        }
    )
    cached = load_json(cache_path) if cache_path and cache_path.is_file() else None
    if isinstance(cached, dict) and cached.get("input_sha256") == input_sha256:
        cached_ids = cached.get("candidate_asset_ids")
        cached_result = cached.get("flash_result")
        cached_mode = cached.get("mode")
        if (
            cached_mode == "deepseek_v4_pro_full_catalog_fallback"
            and isinstance(cached_ids, list)
            and set(cached_ids) == valid_ids
        ):
            filtered = AssetCatalog(
                catalog_id=f"candidates_{catalog.catalog_id}",
                generated_at=catalog.generated_at,
                source_root=catalog.source_root,
                assets=eligible,
                source_catalog_sha256=catalog.source_catalog_sha256,
                warnings=list(catalog.warnings),
            )
            logger.warning("[素材粗筛] 复用 Flash 失败记录，直接将全量素材交给高级模型")
            return filtered, cached, [{"path": prompt.path.as_posix(), "sha256": prompt.sha256}], asset_index
        try:
            cached_selected_refs = (
                _validate_flash_result(cached_result, narration, asset_index)
                if isinstance(cached_result, dict)
                else set()
            )
        except (ValueError, TypeError):
            cached_selected_refs = set()
        cached_selected_ids = {
            asset_index.asset(asset_ref).asset_id for asset_ref in cached_selected_refs
        }
        if (
            isinstance(cached_ids, list)
            and set(cached_ids) <= valid_ids
            and cached_selected_ids
            and cached_selected_ids <= set(cached_ids)
        ):
            filtered = AssetCatalog(
                catalog_id=f"candidates_{catalog.catalog_id}",
                generated_at=catalog.generated_at,
                source_root=catalog.source_root,
                assets=[asset for asset in eligible if asset.asset_id in set(cached_ids)],
                source_catalog_sha256=catalog.source_catalog_sha256,
                warnings=list(catalog.warnings),
            )
            return filtered, cached, [{"path": prompt.path.as_posix(), "sha256": prompt.sha256}], asset_index
    user = json.dumps(
        {
            "case": {
                "case_id": case.case_id,
                "goal": case.goal,
                "feature_path": case.feature_path,
            },
            "narration": narration.model_dump(mode="json"),
            "assets": compact_asset_table(eligible, asset_index),
            "required_asset_refs": sorted(
                {
                    ref
                    for asset_id in required_ids
                    for ref in asset_index.refs_for_asset_id(asset_id)
                }
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raw_result = client.complete_json(
        prompt.text,
        user,
        "asset_coarse_selector",
        max_tokens=4096,
        model=client.coarse_model,
        thinking=False,
    )
    raw_result = _repair_exact_phrase_candidates(raw_result, narration, asset_index)
    phrase_candidates = raw_result.get("phrase_candidates", {}) if isinstance(raw_result, dict) else {}
    has_empty_candidates = any(
        isinstance(candidates, list) and not candidates
        for phrase_map in phrase_candidates.values()
        if isinstance(phrase_map, dict)
        for candidates in phrase_map.values()
    )
    if has_empty_candidates:
        logger.info("[素材粗筛] 检测到空短语候选，开始 Flash 全量目录自审")
        audit_user = json.dumps(
            {
                "original_input": json.loads(user),
                "previous_json": raw_result,
                "audit_instruction": (
                    "复查 previous_json 中每一个空的 phrase_candidates。重新扫描完整 assets.rows："
                    "result_item 只能补入语义精确对应的 result_image；supporting 应补入真实入口、参数页、"
                    "工具列表或编辑页。确实不存在才保留空数组，不得用近义功能冒充。返回审查后的完整 JSON。"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raw_result = client.complete_json(
            prompt.text + "\n这是空候选召回自审轮次，必须重新扫描完整素材表并返回完整 JSON。",
            audit_user,
            "asset_coarse_selector_empty_audit",
            max_tokens=4096,
            model=client.coarse_model,
            thinking=False,
        )
        raw_result = _repair_exact_phrase_candidates(raw_result, narration, asset_index)
    last_error: Exception | None = None
    flash_failed = False
    for contract_attempt in range(3):
        try:
            selected_refs = _validate_flash_result(raw_result, narration, asset_index)
            selected = {asset_index.asset(asset_ref).asset_id for asset_ref in selected_refs}
            break
        except (ValueError, TypeError) as exc:
            last_error = exc
            if contract_attempt == 2:
                flash_failed = True
                break
            logger.warning(
                "[素材粗筛] Flash 契约校验失败，开始第 %d 次纠错: %s",
                contract_attempt + 1,
                exc,
            )
            correction_user = json.dumps(
                {
                    "original_input": json.loads(user),
                    "previous_invalid_json": raw_result,
                    "validation_error": str(exc),
                    "correction_instruction": (
                        "根据 validation_error 修正上一版并返回完整 JSON。phrase_candidates 在没有精确素材时"
                        "必须返回空数组，不得用近义素材填充。所有 asset_ref 必须逐字复制自 "
                        "original_input.assets.rows 的 asset_ref 列；不得凭记忆改写、缩写或编造引用。"
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            raw_result = client.complete_json(
                prompt.text + "\n这是契约纠错轮次，必须修正 validation_error 并重新输出完整 JSON。",
                correction_user,
                "asset_coarse_selector_correction",
                max_tokens=4096,
                model=client.coarse_model,
                thinking=False,
            )
            raw_result = _repair_exact_phrase_candidates(raw_result, narration, asset_index)
    else:  # pragma: no cover - the loop either succeeds or raises
        raise ValueError(f"Flash asset selection correction failed: {last_error}")
    traces.append({"path": prompt.path.as_posix(), "sha256": prompt.sha256})
    if flash_failed:
        selected = set(valid_ids)
        included_relationships = [
            relationship
            for relationship in relationships
            if _relationship_asset_ids(relationship) <= valid_ids
        ]
        mode = "deepseek_v4_pro_full_catalog_fallback"
        logger.warning(
            "[素材粗筛] Flash 连续纠错失败，跳过粗筛并将 %d 个素材交给高级模型: %s",
            len(selected),
            last_error,
        )
    else:
        selected.update(required_ids)
        mode = "deepseek_v4_flash"
        selected, included_relationships = _relationship_closure(selected, relationships, valid_ids)
    if not selected:
        raise ValueError("asset candidate selection produced an empty pool")
    filtered = AssetCatalog(
        catalog_id=f"candidates_{catalog.catalog_id}",
        generated_at=catalog.generated_at,
        source_root=catalog.source_root,
        assets=[asset for asset in eligible if asset.asset_id in selected],
        source_catalog_sha256=catalog.source_catalog_sha256,
        warnings=list(catalog.warnings),
    )
    report = {
        "schema_version": 1,
        "input_sha256": input_sha256,
        "mode": mode,
        "feature_path": case.feature_path,
        "candidate_asset_ids": [asset.asset_id for asset in filtered.assets],
        "candidate_asset_refs": [asset_index.ref_for_asset(asset) for asset in filtered.assets],
        "candidate_count": len(filtered.assets),
        "required_asset_ids": sorted(required_ids),
        "relationships": included_relationships,
        "flash_result": None if flash_failed else raw_result,
        "ai_asset_index_sha256": asset_index.manifest()["index_sha256"],
    }
    if flash_failed:
        report["flash_failure"] = {
            "error": str(last_error),
            "last_invalid_result": raw_result,
            "fallback": "full_catalog_to_pro",
        }
    if cache_path:
        write_json_atomic(cache_path, report)
    return filtered, report, traces, asset_index
