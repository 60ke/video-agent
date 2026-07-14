from __future__ import annotations

import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SKIPPED_PATH_PARTS = {".git", ".hyperframes", "__pycache__", "capture", "node_modules", "renders"}
REFERENCE_TERMS = ("界面", "主界面", "网站", "上传", "操作", "修改", "规格信息", "售后服务", "应用场景", "图层", "实景图", "平面图")
FEATURE_BY_NAME = {
    "门头": "门头招牌",
    "门店招牌": "门头招牌",
    "IP": "IP形象",
    "柯幻熊猫IP": "IP形象",
    "品牌LOGO": "LOGO",
}


def _iter_source_images(source_dir: Path) -> Iterable[Path]:
    for path in sorted(source_dir.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        relative_parts = {part.lower() for part in path.relative_to(source_dir).parts[:-1]}
        if relative_parts.intersection(SKIPPED_PATH_PARTS):
            continue
        yield path


def _safe_label(value: str) -> str:
    value = re.sub(r"\s*\(\d+\)", "", value).strip()
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value)
    return value or "案例"


def _feature_for(source: Path, source_dir: Path) -> str:
    relative = source.relative_to(source_dir)
    module = relative.parts[0] if relative.parts else "综合"
    if "vi-project" in relative.parts:
        module = "VI"
    stem = _safe_label(source.stem)
    if module == "综合":
        return FEATURE_BY_NAME.get(stem, stem)
    if module == "美陈" and stem in FEATURE_BY_NAME:
        return FEATURE_BY_NAME[stem]
    return module


def _asset_kind(source: Path) -> str:
    stem = source.stem
    english_ui_name = any(term in stem.lower() for term in ("interface", "main-ui", "vi-design"))
    return "参考图" if english_ui_name or any(term in stem for term in REFERENCE_TERMS) else "结果图"


def _image_info(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _existing_hashes(*directories: Path) -> dict[str, Path]:
    hashes: dict[str, Path] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                hashes.setdefault(sha256_file(path), path)
    return hashes


def _next_name(destination_dir: Path, feature: str, label: str, kind: str, suffix: str) -> Path:
    prefix = f"柯幻熊猫_文生图_{feature}_{label}_{kind}_"
    for sequence in range(1, 1000):
        candidate = destination_dir / f"{prefix}{sequence:02d}{suffix.lower()}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many imported variants for {feature}/{label}/{kind}")


def _result_index_item(path: Path, feature: str, label: str, sequence: str, source: Path, digest: str) -> dict[str, Any]:
    width, height = _image_info(path)
    return {
        "asset_filename": path.name,
        "feature_path": ["文生图", feature],
        "feature_id": feature,
        "variant_kind": "external_video_material",
        "industry_label": label,
        "content_type": "curated_external_result",
        "sequence": sequence,
        "supported_claims": ["curated_result_image", f"{feature}结果展示", f"{label}案例"],
        "source_staging": source.as_posix(),
        "source_sha256": digest,
        "width": width,
        "height": height,
    }


def _reference_index_item(path: Path, feature: str, label: str, source: Path, digest: str) -> dict[str, Any]:
    width, height = _image_info(path)
    return {
        "asset_filename": path.name,
        "feature_path": ["文生图", feature],
        "reference_label": label,
        "content_type": "curated_external_reference",
        "source_staging": source.as_posix(),
        "source_sha256": digest,
        "width": width,
        "height": height,
    }


def _existing_index_items(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path) if path.is_file() else {}
    return [item for item in payload.get("assets", []) if isinstance(item, dict) and item.get("asset_filename")]


def import_video_material_images(repo_root: Path, source_dir: Path) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source directory is missing: {source_dir}")

    source_label = _safe_label(source_dir.name)
    assets_dir = repo_root / "assets"
    results_dir = assets_dir / "results"
    references_dir = assets_dir / "references"
    import_dir = assets_dir / "imports" / source_label
    results_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)
    import_dir.mkdir(parents=True, exist_ok=True)

    known_hashes = _existing_hashes(results_dir, references_dir)
    seen_source_hashes: dict[str, Path] = {}
    result_index_path = results_dir / f"_{source_label}_导入结果_index.json"
    reference_index_path = references_dir / f"_{source_label}_导入参考_index.json"
    result_items = _existing_index_items(result_index_path)
    reference_items = _existing_index_items(reference_index_path)
    indexed_result_names = {str(item["asset_filename"]) for item in result_items}
    indexed_reference_names = {str(item["asset_filename"]) for item in reference_items}
    records: list[dict[str, Any]] = []
    sequences: dict[tuple[str, str, str], int] = defaultdict(int)

    for source in _iter_source_images(source_dir):
        digest = sha256_file(source)
        feature = _feature_for(source, source_dir)
        label = _safe_label(source.stem)
        kind = _asset_kind(source)
        record: dict[str, Any] = {
            "source_path": source.as_posix(),
            "source_sha256": digest,
            "feature_path": ["文生图", feature],
            "label": label,
            "kind": kind,
        }
        if digest in seen_source_hashes:
            record.update({"status": "duplicate_source", "canonical_source_path": seen_source_hashes[digest].as_posix()})
            records.append(record)
            continue
        seen_source_hashes[digest] = source
        if digest in known_hashes:
            record.update({"status": "already_registered", "canonical_output_path": known_hashes[digest].as_posix()})
            records.append(record)
            continue

        destination_dir = results_dir if kind == "结果图" else references_dir
        sequence_key = (feature, label, kind)
        sequences[sequence_key] += 1
        destination = _next_name(destination_dir, feature, label, kind, source.suffix)
        shutil.copy2(source, destination)
        known_hashes[digest] = destination
        record.update({"status": "imported", "output_path": destination.as_posix(), "output_sha256": sha256_file(destination)})
        records.append(record)
        if kind == "结果图":
            item = _result_index_item(destination, feature, label, f"{sequences[sequence_key]:02d}", source, digest)
            if item["asset_filename"] not in indexed_result_names:
                result_items.append(item)
                indexed_result_names.add(item["asset_filename"])
        else:
            item = _reference_index_item(destination, feature, label, source, digest)
            if item["asset_filename"] not in indexed_reference_names:
                reference_items.append(item)
                indexed_reference_names.add(item["asset_filename"])

    result_index = {
        "schema_version": 1,
        "status": "ready",
        "library": "assets/results",
        "source_library": source_dir.as_posix(),
        "workflow": "external_video_material_import",
        "asset_count": len(result_items),
        "assets": result_items,
    }
    reference_index = {
        "schema_version": 1,
        "status": "ready",
        "library": "assets/references",
        "source_library": source_dir.as_posix(),
        "workflow": "external_video_material_import",
        "asset_count": len(reference_items),
        "assets": reference_items,
    }
    write_json_atomic(result_index_path, result_index)
    write_json_atomic(reference_index_path, reference_index)
    write_json_atomic(
        import_dir / "manifest.json",
        {
            "schema_version": 1,
            "generated_at": utc_now(),
            "source_directory": source_dir.as_posix(),
            "workflow": "external_video_material_import",
            "records": records,
            "summary": {
                "discovered": len(records),
                "imported_results": len(result_items),
                "imported_references": len(reference_items),
                "duplicate_source": sum(item["status"] == "duplicate_source" for item in records),
                "already_registered": sum(item["status"] == "already_registered" for item in records),
            },
        },
    )
    return {"discovered": len(records), "imported_results": len(result_items), "imported_references": len(reference_items), "manifest": (import_dir / "manifest.json").as_posix()}
