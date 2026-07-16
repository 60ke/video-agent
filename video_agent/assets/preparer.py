from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

from PIL import Image

from video_agent.contracts import (
    ActionScene,
    ActionScenePlan,
    Asset,
    AssetCatalog,
    DeriveKind,
    DerivedAssetRequest,
    MaterializationPlan,
    SceneGalleryItem,
)

from .materializer import materialize_assets
from video_agent.io import sha256_file, utc_now


def _request_id(kind: DeriveKind, source: Asset, related: list[str], instruction: str) -> str:
    digest = hashlib.sha256(
        f"{kind.value}|{source.sha256}|{'|'.join(related)}|{instruction}".encode("utf-8")
    ).hexdigest()[:16]
    return f"prepare_{digest}"


def _request(
    scene: ActionScene,
    kind: DeriveKind,
    source: Asset,
    instruction: str,
    output_role: str,
    *,
    related: list[str] | None = None,
    target_orientation: str = "portrait",
) -> DerivedAssetRequest:
    related_ids = related or []
    return DerivedAssetRequest(
        request_id=_request_id(kind, source, related_ids, instruction),
        source_asset_id=source.asset_id,
        related_asset_ids=related_ids,
        derive_kind=kind,
        instruction=instruction,
        output_role=output_role,
        semantic_path=scene.feature_path or source.semantic_path,
        tags=[*scene.feature_path, kind.value, scene.scene_id],
        purpose="asset_preflight",
        scene_id=scene.scene_id,
        semantic_phrase=scene.semantic_phrase,
        target_orientation=target_orientation,
        preserve=["主体内容", "主要文字", "品牌与配色"],
        relationship_id=scene.relationship_group_id,
    )


def _load_relationships(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [item for item in payload.get("relationships", []) if isinstance(item, dict)]


def _write_relationships(path: Path, relationships: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "relationships": relationships}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _relationship_for_result(relationships: list[dict[str, Any]], result_id: str) -> dict[str, Any] | None:
    return next((item for item in relationships if item.get("result_asset_id") == result_id), None)


def _orientation(ratio: float) -> str:
    if ratio >= 1.2:
        return "landscape"
    if ratio <= 0.82:
        return "portrait"
    return "square"


def _same_orientation(left: Asset, right: Asset) -> bool:
    return _orientation(left.width / max(1, left.height)) == _orientation(right.width / max(1, right.height))


def _load_config(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "config" / "asset_preparation.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid asset preparation config: {path}") from exc
    return payload if isinstance(payload, dict) else {}


def _asset_path(repo_root: Path, asset: Asset) -> Path:
    path = Path(asset.path)
    return path if path.is_absolute() else repo_root / path


def _apply_replacements(
    repo_root: Path,
    catalog: AssetCatalog,
    config: dict[str, Any],
) -> tuple[AssetCatalog, list[dict[str, Any]]]:
    requests = config.get("replacement", {}).get("requests", [])
    if not isinstance(requests, list) or not requests:
        return catalog, []
    specifications = {str(item.get("asset_id")): item for item in requests if isinstance(item, dict) and item.get("asset_id")}
    updated: list[Asset] = []
    report: list[dict[str, Any]] = []
    for asset in catalog.assets:
        spec = specifications.get(asset.asset_id)
        if not spec or asset.media_type != "image":
            updated.append(asset)
            continue
        source = _asset_path(repo_root, asset)
        minimum_width = max(1, int(spec.get("minimum_width", asset.width)))
        minimum_height = max(1, int(spec.get("minimum_height", asset.height)))
        if asset.width >= minimum_width and asset.height >= minimum_height:
            updated.append(asset)
            continue
        print(f"[素材修复] 正在调整原图分辨率：{asset.filename}")
        old_sha = asset.sha256
        with Image.open(source) as opened:
            keep_alpha = source.suffix.lower() == ".png" and opened.mode in {"RGBA", "LA"}
            image = opened.convert("RGBA" if keep_alpha else "RGB")
            scale = max(minimum_width / image.width, minimum_height / image.height)
            target = (round(image.width * scale), round(image.height * scale))
            resized = image.resize(target, Image.Resampling.LANCZOS)
            temporary = source.with_name(f".{source.stem}.replacement{source.suffix}")
            save_kwargs: dict[str, Any] = {"quality": 95} if source.suffix.lower() in {".jpg", ".jpeg", ".webp"} else {}
            resized.save(temporary, **save_kwargs)
        os.replace(temporary, source)
        new_sha = sha256_file(source)
        updated.append(
            asset.model_copy(
                update={
                    "sha256": new_sha,
                    "width": target[0],
                    "height": target[1],
                    "metadata": {
                        **asset.metadata,
                        "replaced_from_sha256": old_sha,
                        "replacement_recipe": "lanczos_resolution_repair_v1",
                    },
                }
            )
        )
        report.append({"asset_id": asset.asset_id, "old_sha256": old_sha, "new_sha256": new_sha, "size": list(target)})
        print("[素材修复] 已使用新图替换原图，旧文件已删除")
    if not report:
        return catalog, report
    return AssetCatalog(
        catalog_id=f"replaced_{catalog.catalog_id}",
        generated_at=utc_now(),
        source_root=catalog.source_root,
        assets=updated,
        source_catalog_sha256=catalog.source_catalog_sha256,
        warnings=list(catalog.warnings),
    ), report


def prepare_scene_assets(
    repo_root: Path,
    catalog: AssetCatalog,
    plan: ActionScenePlan,
) -> tuple[AssetCatalog, ActionScenePlan, dict[str, Any]]:
    print(f"[素材准备] 正在检查 {len(plan.scenes)} 个场景的素材完整性...")
    config = _load_config(repo_root)
    gallery_ratio_factor = float(config.get("gallery", {}).get("maximum_ratio_factor", 1.8))
    catalog, replacement_report = _apply_replacements(repo_root, catalog, config)
    assets = {asset.asset_id: asset for asset in catalog.assets}
    relationships_path = repo_root / "assets" / "relationships.json"
    relationships = _load_relationships(relationships_path)
    relationship_by_id = {str(item.get("relationship_id")): item for item in relationships if item.get("relationship_id")}
    strict_causal_kinds = {DeriveKind.RESULT_TO_REFERENCE_MOCK, DeriveKind.RESULT_TO_FLAT_PLAN}
    requests: dict[str, DerivedAssetRequest] = {
        request.request_id: request
        for request in plan.derivation_requests
        if request.derive_kind not in strict_causal_kinds
    }
    retained_ids = set(requests)
    scene_requests: dict[str, list[str]] = {
        scene.scene_id: [request_id for request_id in scene.derivation_request_ids if request_id in retained_ids]
        for scene in plan.scenes
    }
    gallery_replacements: dict[tuple[str, str], str] = {}
    strict_binding_overrides: dict[tuple[str, str], str] = {}
    report: dict[str, Any] = {"checked_scenes": len(plan.scenes), "generated": [], "reused": [], "replacements": replacement_report, "gallery_outliers": [], "relationships": []}

    for scene in plan.scenes:
        if scene.scene_kind == "result_gallery" and len(scene.gallery_items) >= 2:
            group_assets = [assets[item.asset_id] for item in scene.gallery_items]
            ratios = [(asset.width or 1) / (asset.height or 1) for asset in group_assets]
            median_ratio = statistics.median(ratios)
            print(f"[素材准备] 正在检查多图轮播格式：{len(group_assets)} 张")
            for item, asset, ratio in zip(scene.gallery_items, group_assets, ratios, strict=True):
                if abs(math.log(max(0.01, ratio) / max(0.01, median_ratio))) <= math.log(gallery_ratio_factor):
                    continue
                instruction = (
                    f"为同组快速轮播制作与主要比例 {median_ratio:.3f} 一致的预览图；"
                    "保留最有辨识度的主体，不压扁长图，不新增文字或设计内容"
                )
                request = _request(
                    scene,
                    DeriveKind.GALLERY_PREVIEW,
                    asset,
                    instruction,
                    "gallery_preview",
                    target_orientation=_orientation(median_ratio),
                )
                requests[request.request_id] = request
                scene_requests[scene.scene_id].append(request.request_id)
                gallery_replacements[(scene.scene_id, asset.asset_id)] = request.request_id
                report["gallery_outliers"].append({"scene_id": scene.scene_id, "asset_id": asset.asset_id, "ratio": ratio, "group_ratio": median_ratio})
            scene_outliers = [item for item in report["gallery_outliers"] if item["scene_id"] == scene.scene_id]
            if scene_outliers:
                print(f"[素材准备] 发现 {len(scene_outliers)} 张轮播素材格式异常")

        if scene.scene_kind == "reference_to_result":
            print("[素材准备] 正在检查因果素材关系：参考图 -> 结果图")
            result = assets[scene.asset_bindings["output"]]
            relation = _relationship_for_result(relationships, result.asset_id)
            reference_id = relation.get("reference_asset_id") if relation else None
            if reference_id in assets and _same_orientation(assets[str(reference_id)], result):
                strict_binding_overrides[(scene.scene_id, "input")] = str(reference_id)
                continue
            instruction = "根据该结果图反推同一机位、同一空间结构的未设计实景参考图，用于展示上传参考图后生成效果的严格因果流程"
            request = _request(
                scene,
                DeriveKind.RESULT_TO_REFERENCE_MOCK,
                result,
                instruction,
                "reference_image",
                target_orientation=_orientation(result.width / max(1, result.height)),
            )
            requests[request.request_id] = request
            scene_requests[scene.scene_id].append(request.request_id)

        if scene.scene_kind == "result_to_flat_plan":
            print("[素材准备] 正在检查因果素材关系：结果图 -> 平面图")
            result = assets[scene.asset_bindings["input"]]
            relation = _relationship_for_result(relationships, result.asset_id)
            flat_id = relation.get("flat_plan_asset_id") if relation else None
            if flat_id in assets and _same_orientation(assets[str(flat_id)], result):
                strict_binding_overrides[(scene.scene_id, "output")] = str(flat_id)
                continue
            instruction = "基于同一结果图生成严格对应的正视平面设计图，保留主题、主要文字、图形、颜色和空间关系"
            request = _request(
                scene,
                DeriveKind.RESULT_TO_FLAT_PLAN,
                result,
                instruction,
                "plane_result",
                target_orientation=_orientation(result.width / max(1, result.height)),
            )
            requests[request.request_id] = request
            scene_requests[scene.scene_id].append(request.request_id)

    materialization = MaterializationPlan(case_id=plan.case_id, requests=list(requests.values()))
    report["requests"] = [request.model_dump(mode="json", exclude_none=True) for request in materialization.requests]
    derivative_config = config.get("derivatives", {})
    generated_root = repo_root / str(derivative_config.get("root", "assets/derived/generated"))
    registry_path = repo_root / str(derivative_config.get("registry", "assets/derived/generated/registry.json"))
    prepared_catalog = materialize_assets(
        repo_root,
        catalog,
        materialization,
        generated_root,
        registry_path=registry_path,
    ) if materialization.requests else catalog
    prepared_assets = {asset.asset_id: asset for asset in prepared_catalog.assets}
    by_request = {
        str(asset.metadata.get("request_id")): asset
        for asset in prepared_catalog.assets
        if asset.metadata.get("request_id")
    }

    resolved_scenes: list[ActionScene] = []
    reference_by_feature: dict[tuple[str, ...], str] = {
        tuple(str(part) for part in relation.get("feature_path", [])): str(relation["reference_asset_id"])
        for relation in relationships
        if relation.get("reference_asset_id") in prepared_assets and relation.get("feature_path")
    }
    reference_by_feature.update({
        tuple(request.semantic_path): by_request[request_id].asset_id
        for request_id, request in requests.items()
        if request.derive_kind == DeriveKind.RESULT_TO_REFERENCE_MOCK and request_id in by_request
    })
    for scene in plan.scenes:
        bindings = dict(scene.asset_bindings)
        for (override_scene_id, role), asset_id in strict_binding_overrides.items():
            if override_scene_id == scene.scene_id:
                bindings[role] = asset_id
        gallery = list(scene.gallery_items)
        request_ids = scene_requests.get(scene.scene_id, [])
        for request_id in request_ids:
            derived = by_request.get(request_id)
            request = requests.get(request_id)
            if not derived or not request:
                continue
            report["generated"].append({"request_id": request_id, "asset_id": derived.asset_id, "derive_kind": request.derive_kind.value})
            if request.derive_kind == DeriveKind.GALLERY_PREVIEW:
                gallery_replacements[(scene.scene_id, request.source_asset_id)] = derived.asset_id
            elif request.derive_kind in {DeriveKind.RESULT_TO_EDITOR_COMPOSITE}:
                bindings["primary"] = derived.asset_id
            elif request.derive_kind == DeriveKind.RESULT_TO_EDIT_STATE:
                bindings["output"] = derived.asset_id
            elif request.derive_kind == DeriveKind.RESULT_TO_REFERENCE_MOCK:
                bindings["input"] = derived.asset_id
            elif request.derive_kind == DeriveKind.RESULT_TO_FLAT_PLAN:
                bindings["output"] = derived.asset_id
            elif scene.scene_kind == "reference_input":
                bindings["primary"] = derived.asset_id
            else:
                bindings["primary"] = derived.asset_id

        if scene.scene_kind == "result_gallery":
            new_gallery: list[SceneGalleryItem] = []
            for item in gallery:
                replacement = gallery_replacements.get((scene.scene_id, item.asset_id), item.asset_id)
                for key, asset_id in list(bindings.items()):
                    if asset_id == item.asset_id:
                        bindings[key] = replacement
                new_gallery.append(item.model_copy(update={"asset_id": replacement}))
            gallery = new_gallery

        if scene.scene_kind == "reference_input" and tuple(scene.feature_path) in reference_by_feature:
            bindings["primary"] = reference_by_feature[tuple(scene.feature_path)]

        relationship_id = scene.relationship_group_id
        if scene.scene_kind in {"reference_to_result", "result_to_flat_plan", "editor_before_after", "editor_workspace"}:
            source_result_id = scene.asset_bindings.get("output") if scene.scene_kind == "reference_to_result" else scene.asset_bindings.get("input") or next(iter(scene.asset_bindings.values()))
            relation = _relationship_for_result(relationships, source_result_id)
            if relation is None:
                relationship_id = f"rel_{hashlib.sha256(source_result_id.encode('utf-8')).hexdigest()[:12]}"
                relation = {"relationship_id": relationship_id, "feature_path": scene.feature_path, "result_asset_id": source_result_id}
                relationships.append(relation)
                relationship_by_id[relationship_id] = relation
            relationship_id = str(relation["relationship_id"])
            if scene.scene_kind == "reference_to_result":
                relation["reference_asset_id"] = bindings["input"]
                relation["result_asset_id"] = bindings["output"]
            elif scene.scene_kind == "result_to_flat_plan":
                relation["flat_plan_asset_id"] = bindings["output"]
            elif scene.scene_kind == "editor_workspace":
                relation["editor_composite_asset_id"] = bindings.get("primary") or bindings["page"]
                if bindings.get("modal"):
                    relation["editor_modal_asset_id"] = bindings["modal"]
            elif scene.scene_kind == "editor_before_after":
                relation["edited_result_asset_id"] = bindings["output"]
            report["relationships"].append({"scene_id": scene.scene_id, "relationship_id": relationship_id})

        unknown = set(bindings.values()) - set(prepared_assets)
        if unknown:
            raise ValueError(f"[素材准备失败] 场景仍引用缺失素材：{scene.scene_id}/{sorted(unknown)}")
        resolved_scenes.append(
            scene.model_copy(
                update={
                    "asset_bindings": bindings,
                    "gallery_items": gallery,
                    "derivation_request_ids": [],
                    "relationship_group_id": relationship_id,
                    "fallback_policy": "exact",
                }
            )
        )

    _write_relationships(relationships_path, relationships)
    print("[素材注册] 已更新持久化素材和关系注册")
    resolved = ActionScenePlan(
        case_id=plan.case_id,
        timing_lock_sha256=plan.timing_lock_sha256,
        scenes=resolved_scenes,
        derivation_requests=[],
    )
    return prepared_catalog, resolved, report
