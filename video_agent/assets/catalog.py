from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Iterable

import cv2
from PIL import Image

from video_agent.contracts.assets import (
    Asset,
    AssetCatalog,
    AssetQuality,
    EvidenceClass,
    NormalizedRect,
    Provenance,
    VisualAnchor,
)
from video_agent.io import sha256_file, sha256_json, utc_now, write_json_atomic


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ANIMATION_SUFFIXES = {".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}
SITE_ROLE_BY_CAPTURE = {
    "功能入口截图": "feature_entry",
    "功能列表截图": "feature_list",
    "参数面板截图": "feature_form_params",
    "原始桌面截图": "site_home",
    "网站主页截图": "site_home",
}


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _asset_id(kind: str, digest: str) -> str:
    safe_kind = re.sub(r"[^a-z0-9]+", "_", kind.lower()).strip("_") or "media"
    return f"asset_{safe_kind}_{digest[:12]}"


def _image_size(path: Path) -> tuple[int | None, int | None, list[str]]:
    checks: list[str] = []
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
        checks.append("image_decode_ok")
        return width, height, checks
    except Exception as exc:  # noqa: BLE001
        checks.append(f"image_decode_failed:{exc.__class__.__name__}")
        return None, None, checks


def _motion_info(path: Path) -> tuple[int | None, int | None, float | None, int | None, int | None, list[str]]:
    checks: list[str] = []
    try:
        if path.suffix.lower() in ANIMATION_SUFFIXES:
            with Image.open(path) as image:
                frame_count = int(getattr(image, "n_frames", 1))
                durations = []
                for frame_index in range(frame_count):
                    image.seek(frame_index)
                    durations.append(max(1, int(image.info.get("duration", 100))))
                duration_ms = sum(durations)
                fps = frame_count * 1000 / duration_ms
                checks.append("animation_decode_ok")
                return image.width, image.height, fps, frame_count, duration_ms, checks
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError("unable to open video")
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        capture.release()
        if width <= 0 or height <= 0 or fps <= 0 or frame_count <= 0:
            raise ValueError("invalid video metadata")
        duration_ms = int(round(frame_count * 1000 / fps))
        checks.append("video_decode_ok")
        return width, height, fps, frame_count, duration_ms, checks
    except Exception as exc:  # noqa: BLE001
        checks.append(f"motion_decode_failed:{exc.__class__.__name__}")
        return None, None, None, None, None, checks


def _rect(value: Any) -> NormalizedRect | None:
    if not isinstance(value, dict):
        return None
    try:
        return NormalizedRect.model_validate(value)
    except Exception:  # noqa: BLE001
        return None


def _same_rect(a: NormalizedRect, b: NormalizedRect) -> bool:
    return max(abs(a.x - b.x), abs(a.y - b.y), abs(a.w - b.w), abs(a.h - b.h)) <= 0.002


def _anchors_for(filename: str, callout_payload: dict[str, Any]) -> tuple[list[VisualAnchor], list[str]]:
    warnings: list[str] = []
    item = callout_payload.get("items", {}).get(filename, {}) if isinstance(callout_payload, dict) else {}
    raw = item.get("callouts", []) if isinstance(item, dict) else []
    anchors: list[VisualAnchor] = []
    for idx, callout in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(callout, dict):
            continue
        rect = _rect(callout.get("box"))
        if rect is None:
            warnings.append(f"{filename}: invalid callout box at index {idx}")
            continue
        label = str(callout.get("target_label") or f"target_{idx + 1}").strip()
        role = str(callout.get("target_role") or callout.get("type") or "focus").strip()
        if any(existing.label == label and existing.role == role and _same_rect(existing.rect, rect) for existing in anchors):
            continue
        panel_rect = _rect(callout.get("panel_box"))
        anchor_key = f"{filename}|{label}|{role}|{rect.model_dump_json()}"
        anchors.append(
            VisualAnchor(
                anchor_id=f"anchor_{_short_hash(anchor_key)}",
                label=label,
                role=role,
                intent=str(callout.get("intent") or "focus"),
                rect=rect,
                panel_rect=panel_rect,
                source="cdp",
                confidence=1.0,
            )
        )
    return anchors, warnings


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _result_metadata(results_dir: Path) -> dict[str, dict[str, Any]]:
    by_filename: dict[str, dict[str, Any]] = {}
    for path in sorted(results_dir.glob("_*index.json")):
        payload = _load_json(path)
        for item in payload.get("assets", []) if isinstance(payload.get("assets"), list) else []:
            if isinstance(item, dict) and item.get("asset_filename"):
                by_filename[str(item["asset_filename"])] = item
    return by_filename


def _reference_metadata(references_dir: Path) -> dict[str, dict[str, Any]]:
    by_filename: dict[str, dict[str, Any]] = {}
    for path in sorted(references_dir.glob("_*index.json")):
        payload = _load_json(path)
        for item in payload.get("assets", []) if isinstance(payload.get("assets"), list) else []:
            if isinstance(item, dict) and item.get("asset_filename"):
                by_filename[str(item["asset_filename"])] = item
    return by_filename


def _site_semantics(path: Path) -> tuple[list[str], str, list[str]]:
    parts = path.stem.split("_")
    warnings: list[str] = []
    if path.stem == "柯幻熊猫_网站_主页_原始桌面截图":
        return ["网站", "主页"], "site_home", warnings
    if path.stem == "柯幻熊猫_AI工具_功能列表截图":
        # Filename legacy says AI工具; asset is the 文生图 editor-tools list page (role=other).
        return ["文生图", "编辑小工具"], "other", warnings
    capture = parts[-1] if parts else ""
    role = SITE_ROLE_BY_CAPTURE.get(capture, "site_screenshot")
    if len(parts) < 3:
        warnings.append(f"unrecognized site filename: {path.name}")
        return parts[1:-1], role, warnings
    semantic = parts[1:-1]
    if semantic == ["文生图", "图文广告", "易拉宝", "展架"]:
        semantic = ["文生图", "图文广告", "易拉宝/展架"]
    return semantic, role, warnings


def _result_filename_semantics(parts: list[str]) -> tuple[list[str], int]:
    if parts[1:5] == ["文生图", "图文广告", "易拉宝", "展架"]:
        return ["文生图", "图文广告", "易拉宝/展架"], 5
    if len(parts) >= 6 and parts[2] == "图文广告":
        return parts[1:4], 4
    return parts[1:3], 3


def _result_semantics(path: Path, metadata: dict[str, Any]) -> tuple[list[str], str, list[str], list[str]]:
    feature_path = metadata.get("feature_path")
    if isinstance(feature_path, list) and feature_path:
        semantic = [str(item) for item in feature_path]
    else:
        parts = path.stem.split("_")
        semantic, _ = _result_filename_semantics(parts)
    variant = str(metadata.get("brand_label") or metadata.get("industry_label") or "").strip()
    if not variant:
        parts = path.stem.split("_")
        _, consumed = _result_filename_semantics(parts)
        variant_parts = parts[consumed:-2]
        variant = "_".join(variant_parts)
    claims = [str(item) for item in metadata.get("supported_claims", []) if str(item).strip()]
    if not claims:
        claims = ["curated_result_image", f"{' -> '.join(semantic)}结果展示"]
    tags = [variant] if variant else []
    return semantic, variant, claims, tags


def _iter_media(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for child in sorted(root.iterdir(), key=lambda value: value.name):
        if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
            yield child


def _iter_media_recursive(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for child in sorted(root.rglob("*"), key=lambda value: value.as_posix()):
        if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES | ANIMATION_SUFFIXES | VIDEO_SUFFIXES:
            yield child


def _brand_role(path: Path, brand_dir: Path) -> tuple[str, str, list[str]]:
    relative = path.relative_to(brand_dir)
    parts = [part.lower() for part in relative.parts]
    name = path.stem.lower()
    tags = ["柯幻熊猫", "品牌IP"]
    if "logo" in parts:
        return "brand_logo", "image", tags + ["Logo"]
    if "animated" in parts or path.suffix.lower() in ANIMATION_SUFFIXES:
        return "brand_ip_animation", "video", tags + ["动画", "跑步", "透明背景"]
    if "video" in parts or path.suffix.lower() in VIDEO_SUFFIXES:
        action = "挥手" if "挥手" in name else "跑步" if "跑步" in name else "动态"
        return "brand_ip_video", "video", tags + ["视频", action]
    action_tags = []
    for action in ("挥手", "跑步", "跳跃", "护目镜", "平板", "无人机", "比心", "闪电"):
        if action in name:
            action_tags.append(action)
    if name.startswith("熊猫定"):
        action_tags.append("标准形象")
    return "brand_ip_static", "image", tags + ["静态"] + action_tags


def build_catalog(assets_root: Path, output_path: Path | None = None) -> AssetCatalog:
    assets_root = assets_root.resolve()
    sites_dir = assets_root / "sites"
    results_dir = assets_root / "results"
    references_dir = assets_root / "references"
    outro_dir = assets_root / "outro"
    brand_dir = assets_root / "brand"
    derived_site_manifest = assets_root / "derived" / "sites" / "柯幻熊猫" / "文生图" / "功能入口" / "manifest.json"
    derived_params_manifest = assets_root / "derived" / "sites" / "柯幻熊猫" / "文生图" / "参数面板序列" / "manifest.json"
    workflow_scene_manifest = assets_root / "derived" / "workflow_scenes" / "manifest.json"
    prepared_assets_registry = assets_root / "derived" / "generated" / "registry.json"
    callouts = _load_json(sites_dir / "_callouts.json")
    result_meta = _result_metadata(results_dir)
    reference_meta = _reference_metadata(references_dir)
    assets: list[Asset] = []
    warnings: list[str] = []
    for path in _iter_media(sites_dir):
        digest = sha256_file(path)
        width, height, checks = _image_size(path)
        semantic_path, role, filename_warnings = _site_semantics(path)
        anchors, anchor_warnings = _anchors_for(path.name, callouts)
        warnings.extend(filename_warnings + anchor_warnings)
        assets.append(
            Asset(
                asset_id=_asset_id("site", digest),
                path=path.relative_to(assets_root.parent).as_posix(),
                sha256=digest,
                filename=path.name,
                width=width,
                height=height,
                semantic_path=semantic_path,
                role=role,
                production_eligible=True,
                evidence_class=EvidenceClass.SOURCE,
                claims=["real_website_screenshot", role],
                tags=[semantic_path[-1]] if semantic_path else [],
                visual_anchors=anchors,
                quality=AssetQuality(readable=bool(width and height), checks=checks),
                provenance=Provenance(origin="site_screenshot_library"),
                metadata={"capture_type": path.stem.split("_")[-1], "mime_type": mimetypes.guess_type(path.name)[0]},
            )
        )

    if derived_site_manifest.is_file():
        manifest = _load_json(derived_site_manifest)
        for item in manifest.get("assets", []) if isinstance(manifest.get("assets"), list) else []:
            if not isinstance(item, dict):
                continue
            path = Path(str(item.get("output_path") or ""))
            if not path.is_file():
                warnings.append(f"derived site keyframe missing: {path}")
                continue
            digest = sha256_file(path)
            expected = str(item.get("output_sha256") or "")
            if digest != expected:
                warnings.append(f"derived site keyframe hash mismatch: {path.name}")
                continue
            width, height, checks = _image_size(path)
            semantic_path = [str(item.get("module") or "文生图"), *[str(part) for part in item.get("feature_path", [])]]
            assets.append(
                Asset(
                    asset_id=_asset_id("site_keyframe", digest),
                    path=path.relative_to(assets_root.parent).as_posix(),
                    sha256=digest,
                    filename=path.name,
                    width=width,
                    height=height,
                    semantic_path=semantic_path,
                    role="feature_entry",
                    production_eligible=True,
                    evidence_class=EvidenceClass.SEMANTIC,
                    claims=[],
                    tags=[str(item.get("target") or semantic_path[-1]), "9:16", "功能入口", "红色手绘圈"],
                    quality=AssetQuality(readable=True, checks=checks + list(item.get("quality_checks", []))),
                    provenance=Provenance(
                        origin="gpt_image_site_keyframe",
                        parent_asset_ids=[_asset_id("site", str(item.get("source_sha256") or ""))],
                        provider=item.get("provider"),
                        model=item.get("model"),
                        prompt_sha256=item.get("prompt_sha256"),
                        response_id=item.get("response_id"),
                    ),
                    metadata={
                        "source_path": item.get("source_path"),
                        "source_sha256": item.get("source_sha256"),
                        "annotation_style": item.get("annotation_style"),
                        "workflow": manifest.get("workflow"),
                    },
                )
            )

    if derived_params_manifest.is_file():
        manifest = _load_json(derived_params_manifest)
        for item in manifest.get("sequences", []) if isinstance(manifest.get("sequences"), list) else []:
            if not isinstance(item, dict):
                continue
            frames = item.get("frames", {})
            if not isinstance(frames, dict) or any(not isinstance(frames.get(state), dict) for state in ("base", "stage", "final")):
                warnings.append(f"incomplete approved parameter sequence: {item.get('sequence_id')}")
                continue
            paths = {state: Path(str(frames[state].get("path") or "")) for state in ("base", "stage", "final")}
            if any(not path.is_file() for path in paths.values()):
                warnings.append(f"approved parameter sequence file missing: {item.get('sequence_id')}")
                continue
            digests = {state: sha256_file(path) for state, path in paths.items()}
            if any(digests[state] != frames[state].get("sha256") for state in paths):
                warnings.append(f"approved parameter sequence hash mismatch: {item.get('sequence_id')}")
                continue
            asset_ids = {state: _asset_id("site_params_sequence", digest) for state, digest in digests.items()}
            semantic_path = [str(item.get("module") or "文生图"), *[str(part) for part in item.get("feature_path", [])]]
            for state in ("base", "stage", "final"):
                path = paths[state]
                width, height, checks = _image_size(path)
                frame = frames[state]
                assets.append(
                    Asset(
                        asset_id=asset_ids[state], path=path.relative_to(assets_root.parent).as_posix(), sha256=digests[state],
                        filename=path.name, width=width, height=height, semantic_path=semantic_path, role="feature_form_params",
                        production_eligible=True, evidence_class=EvidenceClass.SEMANTIC, claims=[],
                        tags=[str(item.get("feature") or semantic_path[-1]), "9:16", "参数面板", "花字序列", state],
                        quality=AssetQuality(readable=True, checks=checks + list(frame.get("quality_checks", []))),
                        provenance=Provenance(
                            origin="gpt_image_site_keyframe" if frame.get("origin") == "gpt_image_edit" else "deterministic_faithful_derivative",
                            parent_asset_ids=[_asset_id("site", str(item.get("source_sha256") or ""))], provider=frame.get("provider"),
                            model=frame.get("model"), prompt_sha256=item.get("prompt_sha256"), response_id=frame.get("response_id"),
                        ),
                        metadata={
                            "workflow": manifest.get("workflow"), "sequence_id": item.get("sequence_id"), "sequence_role": state,
                            "sequence_asset_ids": asset_ids, "required_field_labels": item.get("required_field_labels", []),
                            "callout_text": item.get("callout_text"), "source_path": item.get("source_path"),
                            "source_sha256": item.get("source_sha256"), "registration": item.get("registration", {}),
                        },
                    )
                )

    # Workflow screens are explicitly curated UI states such as the image
    # editor. They are not inferred from generic screenshots and never use
    # coordinate-time callouts at render time.
    if workflow_scene_manifest.is_file():
        manifest = _load_json(workflow_scene_manifest)
        workflow_items = manifest.get("assets", []) if isinstance(manifest.get("assets"), list) else []
        workflow_asset_ids = {
            str(item.get("sha256")): _asset_id("workflow_scene", str(item.get("sha256")))
            for item in workflow_items
            if isinstance(item, dict) and item.get("sha256")
        }
        sequence_asset_ids: dict[str, dict[str, str]] = {}
        for item in workflow_items:
            if not isinstance(item, dict) or not item.get("editor_flow_sequence_id") or not item.get("editor_flow_role"):
                continue
            sequence_asset_ids.setdefault(str(item["editor_flow_sequence_id"]), {})[str(item["editor_flow_role"])] = workflow_asset_ids.get(str(item.get("sha256")), "")
        for item in workflow_items:
            if not isinstance(item, dict):
                continue
            path = Path(str(item.get("path") or ""))
            if not path.is_file():
                warnings.append(f"approved workflow scene missing: {path}")
                continue
            digest = sha256_file(path)
            if digest != str(item.get("sha256") or ""):
                warnings.append(f"approved workflow scene hash mismatch: {path.name}")
                continue
            width, height, checks = _image_size(path)
            semantic_path = [str(part) for part in item.get("semantic_path", []) if str(part)]
            if len(semantic_path) < 2:
                warnings.append(f"workflow scene lacks semantic path: {path.name}")
                continue
            role = str(item.get("role") or "workflow_scene")
            editor_flow_role = item.get("editor_flow_role")
            source_artwork_sha256 = item.get("source_artwork_sha256")
            parent_ids: list[str] = []
            if source_artwork_sha256:
                parent_ids.append(_asset_id("result", str(source_artwork_sha256)))
            if editor_flow_role == "edited_result" or item.get("derive_kind") in {"edited_result", "result_to_edit_state"}:
                role = "result_image"
                evidence = EvidenceClass.SEMANTIC
                origin = "user_provided_edited_result" if item.get("source") == "user_provided_edited_result" else "gpt_image_editor_flow"
            elif source_artwork_sha256 and editor_flow_role in {"page", "modal"}:
                evidence = EvidenceClass.SEMANTIC
                origin = "gpt_image_editor_flow" if item.get("editor_flow_sequence_id") else "curated_workflow_scene"
            else:
                evidence = EvidenceClass.SOURCE
                origin = "gpt_image_editor_flow" if item.get("editor_flow_sequence_id") else "curated_workflow_scene"
            assets.append(
                Asset(
                    asset_id=_asset_id("workflow_scene", digest), path=path.relative_to(assets_root.parent).as_posix(),
                    sha256=digest, filename=path.name, width=width, height=height, semantic_path=semantic_path,
                    role=role, production_eligible=True, evidence_class=evidence,
                    claims=[] if evidence is EvidenceClass.SEMANTIC else [str(value) for value in item.get("claims", []) if str(value)],
                    tags=[str(value) for value in item.get("tags", []) if str(value)],
                    quality=AssetQuality(readable=True, checks=checks),
                    provenance=Provenance(
                        origin=origin,
                        parent_asset_ids=parent_ids,
                        provider=item.get("provider"), model=item.get("model"), prompt_sha256=item.get("prompt_sha256"),
                        response_id=item.get("response_id"),
                    ),
                    metadata={
                        "workflow_step": item.get("workflow_step"), "source": item.get("source"),
                        "editor_flow_sequence_id": item.get("editor_flow_sequence_id"),
                        "editor_flow_role": editor_flow_role,
                        "derive_kind": item.get("derive_kind") or ("edited_result" if editor_flow_role == "edited_result" else None),
                        "editor_flow_asset_ids": sequence_asset_ids.get(str(item.get("editor_flow_sequence_id")), {}),
                        "source_artwork_path": item.get("source_artwork_path"),
                        "source_artwork_sha256": source_artwork_sha256,
                        "focus_target": item.get("focus_target"), "focus_rect": item.get("focus_rect"),
                    },
                )
            )

    for path in _iter_media(results_dir):
        digest = sha256_file(path)
        width, height, checks = _image_size(path)
        metadata = result_meta.get(path.name, {})
        semantic_path, variant, claims, tags = _result_semantics(path, metadata)
        assets.append(
            Asset(
                asset_id=_asset_id("result", digest),
                path=path.relative_to(assets_root.parent).as_posix(),
                sha256=digest,
                filename=path.name,
                width=width,
                height=height,
                semantic_path=semantic_path,
                role="result_image",
                evidence_class=EvidenceClass.SOURCE,
                claims=claims,
                tags=tags,
                identity_group=variant or None,
                quality=AssetQuality(readable=bool(width and height), checks=checks),
                provenance=Provenance(origin="curated_result_library"),
                metadata={
                    "variant_label": variant,
                    "variant_kind": metadata.get("variant_kind"),
                    "content_type": metadata.get("content_type"),
                    "mime_type": mimetypes.guess_type(path.name)[0],
                },
            )
        )

    for path in _iter_media(references_dir):
        digest = sha256_file(path)
        width, height, checks = _image_size(path)
        metadata = reference_meta.get(path.name, {})
        feature_path = metadata.get("feature_path")
        semantic_path = [str(item) for item in feature_path] if isinstance(feature_path, list) and feature_path else ["文生图", "参考素材"]
        label = str(metadata.get("reference_label") or path.stem).strip()
        assets.append(
            Asset(
                asset_id=_asset_id("reference", digest),
                path=path.relative_to(assets_root.parent).as_posix(),
                sha256=digest,
                filename=path.name,
                width=width,
                height=height,
                semantic_path=semantic_path,
                role="reference_image",
                production_eligible=True,
                evidence_class=EvidenceClass.SOURCE,
                claims=["curated_reference_image", f"{' -> '.join(semantic_path)}参考素材"],
                tags=[label, "参考图"],
                quality=AssetQuality(readable=bool(width and height), checks=checks),
                provenance=Provenance(origin="external_reference_library"),
                metadata={
                    "reference_label": label,
                    "content_type": metadata.get("content_type"),
                    "source_staging": metadata.get("source_staging"),
                    "mime_type": mimetypes.guess_type(path.name)[0],
                },
            )
        )

    for path in _iter_media(outro_dir):
        digest = sha256_file(path)
        media_type = "video" if path.suffix.lower() in VIDEO_SUFFIXES else "image"
        width = height = None
        checks: list[str] = []
        if media_type == "image":
            width, height, checks = _image_size(path)
        assets.append(
            Asset(
                asset_id=_asset_id("outro", digest),
                path=path.relative_to(assets_root.parent).as_posix(),
                sha256=digest,
                media_type=media_type,
                filename=path.name,
                width=width,
                height=height,
                semantic_path=["共享", "片尾"],
                role="outro",
                evidence_class=EvidenceClass.DECORATIVE,
                claims=[],
                tags=["柯幻熊猫", "片尾"],
                quality=AssetQuality(checks=checks),
                provenance=Provenance(origin="shared_outro_library"),
            )
        )

    seen_brand_digests: set[str] = set()
    for path in _iter_media_recursive(brand_dir):
        # The production brand library intentionally contains one shared logo.
        # Customer IP/result images belong to their feature result folders and
        # must never become a generic fallback brand cutaway.
        if path.name != "柯幻熊猫_LOGO.png" or path.parent.name != "logo":
            warnings.append(f"ignored non-production brand asset: {path.relative_to(assets_root).as_posix()}")
            continue
        digest = sha256_file(path)
        if digest in seen_brand_digests:
            warnings.append(f"duplicate brand asset skipped: {path.relative_to(assets_root).as_posix()}")
            continue
        seen_brand_digests.add(digest)
        role, media_type, tags = _brand_role(path, brand_dir)
        fps = frame_count = duration_ms = None
        if media_type == "video":
            width, height, fps, frame_count, duration_ms, checks = _motion_info(path)
        else:
            width, height, checks = _image_size(path)
        canonical = role == "brand_logo" or path.name.startswith("熊猫定-") or path.name == "图层 1.png"
        assets.append(
            Asset(
                asset_id=_asset_id(role, digest),
                path=path.relative_to(assets_root.parent).as_posix(),
                sha256=digest,
                media_type=media_type,
                filename=path.name,
                width=width,
                height=height,
                semantic_path=["品牌", "柯幻熊猫", role],
                role=role,
                evidence_class=EvidenceClass.SOURCE if canonical else EvidenceClass.DECORATIVE,
                claims=["official_brand_identity"] if canonical else [],
                tags=tags,
                identity_group="柯幻熊猫",
                quality=AssetQuality(readable=bool(width and height), checks=checks),
                provenance=Provenance(origin="brand_ip_library"),
                metadata={
                    "fps": fps,
                    "frame_count": frame_count,
                    "duration_ms": duration_ms,
                    "mime_type": mimetypes.guess_type(path.name)[0],
                },
            )
        )

    prepared_payload = _load_json(prepared_assets_registry)
    for item in prepared_payload.get("assets", []) if isinstance(prepared_payload.get("assets"), list) else []:
        try:
            asset = Asset.model_validate(item)
            source = Path(asset.path)
            source = source if source.is_absolute() else assets_root.parent / source
            if not source.is_file() or sha256_file(source) != asset.sha256:
                warnings.append(f"prepared asset missing or changed: {asset.filename}")
                continue
            assets.append(asset)
        except (ValueError, TypeError) as exc:
            warnings.append(f"invalid prepared asset registry item: {exc}")

    catalog = AssetCatalog(
        catalog_id="catalog_video_agent_assets_v3",
        generated_at=utc_now(),
        source_root=assets_root.name,
        assets=assets,
        warnings=warnings,
    )
    catalog.source_catalog_sha256 = sha256_json([asset.model_dump(mode="json") for asset in assets])
    if output_path:
        write_json_atomic(output_path, catalog)
    return catalog


def catalog_snapshot(catalog: AssetCatalog, feature_path: list[str], selected_asset_ids: list[str]) -> AssetCatalog:
    del feature_path
    selected = set(selected_asset_ids)
    assets = list(catalog.assets)
    if selected - {asset.asset_id for asset in assets}:
        missing = ", ".join(sorted(selected - {asset.asset_id for asset in assets}))
        raise ValueError(f"selected asset ids missing from catalog: {missing}")
    return AssetCatalog(
        catalog_id=f"snapshot_{catalog.catalog_id}",
        generated_at=utc_now(),
        source_root=catalog.source_root,
        assets=assets,
        source_catalog_sha256=catalog.source_catalog_sha256,
        warnings=list(catalog.warnings),
    )
