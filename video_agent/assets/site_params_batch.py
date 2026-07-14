from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection

from PIL import Image

from video_agent.assets.flower_text import build_flower_text_assets
from video_agent.assets.materializer import _prompt
from video_agent.contracts import DeriveKind
from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


SUFFIX = "_参数面板截图"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class SiteParamsSource:
    path: Path
    site: str
    module: str
    feature_path: tuple[str, ...]
    feature: str


@dataclass(frozen=True)
class RequiredFieldsAnnotation:
    labels: tuple[str, ...]
    callout_text: str
    frontend_source_path: str
    frontend_source_sha256: str
    cdp_labels: tuple[str, ...]
    cdp_unmatched_labels: tuple[str, ...]


def parse_site_params_filename(path: Path) -> SiteParamsSource:
    stem = path.stem
    if not stem.endswith(SUFFIX):
        raise ValueError(f"not a parameter-panel screenshot: {path.name}")
    parts = stem[: -len(SUFFIX)].split("_")
    if len(parts) < 3:
        raise ValueError(f"parameter-panel filename has too few segments: {path.name}")
    site, module, *feature_parts = parts
    if not feature_parts:
        raise ValueError(f"parameter-panel filename has no feature: {path.name}")
    feature = "/".join(feature_parts)
    return SiteParamsSource(path=path, site=site, module=module, feature_path=tuple(feature_parts), feature=feature)


def _callout_text(labels: tuple[str, ...]) -> str:
    return "填写必填项" if len(labels) > 3 else "+".join(labels)


def _feature_label(source: SiteParamsSource) -> str:
    return "/".join(source.feature_path[1:]) if source.feature_path[0] == "图文广告" else source.feature


def _frontend_sources(repo_root: Path, source: SiteParamsSource) -> list[Path]:
    profile = load_json(repo_root / "references" / "site_profiles" / "kehuanxiongmao.json")
    frontend_root = Path(profile["frontend_code_evidence"]["project_root_hint"])
    if source.feature_path[0] == "图文广告":
        if source.feature_path[-1] == "贴纸":
            return [frontend_root / "src" / "views" / "graphic-ad" / "components" / "StickerLeftFormPanel.vue"]
        base = frontend_root / "src" / "views" / "graphic-ad"
        return [base / "index.vue", base / "components" / "ImageAdLeftFormPanel.vue"]
    registry = load_json(repo_root / "references" / "site_profiles" / "kehuanxiongmao_text_to_image_modules.json")
    module = next((item for item in registry.get("modules", []) if item.get("label") == source.feature), None)
    if not isinstance(module, dict) or not module.get("component"):
        raise ValueError(f"frontend module registry has no component for {source.feature}")
    component = Path(str(module["component"]).removeprefix("@/"))
    return [frontend_root / "src" / component.parent / "components" / "LeftFormPanel.vue"]


def _balanced_section(text: str, start: int, opening: str, closing: str) -> str:
    if start < 0 or start >= len(text) or text[start] != opening:
        raise ValueError("invalid frontend source section")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unterminated frontend source section")


def _unique(labels: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(label.strip() for label in labels if label.strip() and "{{" not in label and "}}" not in label))


def _labels_from_graphic_ad_source(text: str, feature: str) -> tuple[str, ...]:
    marker = f"title: '图文广告-{feature}'"
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"frontend graphic-ad config is missing title: 图文广告-{feature}")
    config_start = text.rfind("{", 0, marker_index)
    config = _balanced_section(text, config_start, "{", "}")
    labels: list[str] = []
    fields_index = config.find("fields:")
    if fields_index >= 0:
        array_start = config.find("[", fields_index)
        fields = _balanced_section(config, array_start, "[", "]")
        index = 0
        while index < len(fields):
            if fields[index] != "{":
                index += 1
                continue
            field = _balanced_section(fields, index, "{", "}")
            label_match = re.search(r"\blabel:\s*'([^']+)'", field)
            if label_match and re.search(r"\brequired:\s*true\b", field):
                labels.append(label_match.group(1))
            index += len(field)
    if re.search(r"\bdescriptionRequired:\s*true\b", config):
        labels.append("补充描述")
    return _unique(labels)


def _label_from_validation_message(message: str) -> str:
    return re.sub(r"^(?:请输入|请选择|请填写|请上传|请补充)", "", message).strip()


def _labels_from_form_component(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in re.finditer(
        r'<el-form-item\s+label="([^"]+)"[^>]*>.*?<span[^>]*class="[^"]*label-required[^"]*"',
        text,
        flags=re.DOTALL,
    ):
        labels.append(match.group(1))
    for match in re.finditer(
        r'<span[^>]*class="[^"]*box-icon-text[^"]*"[^>]*>\s*([^<]+?)\s*</span>\s*<span[^>]*class="[^"]*label-required[^"]*"',
        text,
        flags=re.DOTALL,
    ):
        labels.append(match.group(1))
    explicit = _unique(labels)
    if explicit:
        return explicit
    for match in re.finditer(
        r"\b[A-Za-z_]\w*\s*:\s*\{[^{}]{0,300}\brequired:\s*true\b[^{}]{0,300}\bmessage:\s*'([^']+)'",
        text,
        flags=re.DOTALL,
    ):
        label = _label_from_validation_message(match.group(1))
        if label:
            labels.append(label)
    return _unique(labels)


def _frontend_required_labels(source: SiteParamsSource, frontend_sources: list[Path]) -> tuple[str, ...]:
    text_by_path = {path: path.read_text(encoding="utf-8") for path in frontend_sources}
    if source.feature_path[0] == "图文广告" and _feature_label(source) != "贴纸":
        return _labels_from_graphic_ad_source(text_by_path[frontend_sources[0]], _feature_label(source))
    return _labels_from_form_component("\n".join(text_by_path.values()))


def _required_fields_annotation(repo_root: Path, source: SiteParamsSource, callouts: dict[str, Any]) -> RequiredFieldsAnnotation:
    item = callouts.get("items", {}).get(source.path.name, {})
    raw_callouts = item.get("callouts", []) if isinstance(item, dict) else []
    cdp_labels: list[str] = []
    for callout in raw_callouts if isinstance(raw_callouts, list) else []:
        if not isinstance(callout, dict) or callout.get("intent") != "required_field":
            continue
        label = str(callout.get("target_label") or "").replace("*", "").replace("＊", "").strip()
        if label and label not in cdp_labels:
            cdp_labels.append(label)
    frontend_sources = _frontend_sources(repo_root, source)
    missing_sources = [path for path in frontend_sources if not path.is_file()]
    if missing_sources:
        raise FileNotFoundError(f"frontend source is missing for {source.path.name}: {', '.join(str(path) for path in missing_sources)}")
    frontend_text = "\n".join(path.read_text(encoding="utf-8") for path in frontend_sources)
    frontend_labels = _frontend_required_labels(source, frontend_sources)
    cdp_verified_labels = [label for label in cdp_labels if label in frontend_text]
    stable_labels = _unique([*frontend_labels, *cdp_verified_labels])
    if not stable_labels:
        raise ValueError(f"frontend source has no required fields for {source.path.name}; update the extractor before generating")
    unmatched = tuple(label for label in cdp_labels if label not in cdp_verified_labels)
    return RequiredFieldsAnnotation(
        labels=stable_labels,
        callout_text=_callout_text(stable_labels),
        frontend_source_path=";".join(path.resolve().as_posix() for path in frontend_sources),
        frontend_source_sha256=hashlib.sha256("".join(sha256_file(path) for path in frontend_sources).encode("ascii")).hexdigest(),
        cdp_labels=tuple(cdp_labels),
        cdp_unmatched_labels=unmatched,
    )


def _instruction(source: SiteParamsSource, annotation: RequiredFieldsAnnotation) -> str:
    hierarchy = " -> ".join(source.feature_path)
    return (
        f"文件名解析路径是 {source.site} -> {source.module} -> {hierarchy}，当前功能为‘{source.feature}’。"
        f"新增花字只能逐字写为‘{annotation.callout_text}’，它是唯一允许新增的中文文字，且花字不得包含 * 或 ＊。"
        "页面原有 UI 中已经存在的红色 * 或 ＊ 是界面内容，必须逐个原样保留；不得删除、隐藏、移动、改色、改样式、复制或用花字替换。"
        "绝不可把提示词、校验过程或来源说明渲染进图片，包括‘已验证必填字段’‘必填字段’‘字段说明’‘CDP’‘前端源码’。"
        "花字必须作为直接覆盖在原始参数面板上的独立视觉叠层，优先落在面板右侧或右下区域；不得为了放花字新增右侧黑栏、左右分栏、留出空白区或缩小原始参数面板。"
        "原始参数面板必须从左至右铺满有效画面宽度，两侧外边距各不超过 3%；绝不可在右侧留下空白条、黑色空区或独立侧栏。"
        "花字可以覆盖普通表单内容或页面背景以形成醒目的整合构图，唯一禁止遮挡的是原始页面标题或分区标题。"
        "不要生成箭头、指针、连接线、红色框、规则矩形、圆圈、鼠标或人物头像。最终素材只允许出现参数面板和花字。"
    )


def _output_name(source: SiteParamsSource) -> str:
    return source.path.name.replace("参数面板截图", "参数面板关键帧")


def generate_site_params_keyframes(
    repo_root: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    include: str | None = None,
    exclude: Collection[str] = (),
    workers: int = 2,
    force: bool = False,
) -> dict[str, Any]:
    excluded = set(exclude)
    paths = [
        path
        for path in sorted(source_dir.glob(f"*_文生图_*{SUFFIX}.*"))
        if path.suffix.lower() in IMAGE_SUFFIXES and (include is None or path.name == include) and path.name not in excluded
    ]
    sources = [parse_site_params_filename(path) for path in paths]
    if not sources:
        requested = f" matching {include}" if include else ""
        raise FileNotFoundError(f"no parameter-panel screenshots found in {source_dir}{requested}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    previous = load_json(manifest_path) if manifest_path.is_file() else {}
    callouts = load_json(source_dir / "_callouts.json")
    _, template_sha256 = _prompt(repo_root, DeriveKind.SITE_PARAMS_KEYFRAME, "{batch_instruction}")

    def write_manifest(results: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
        write_json_atomic(
            manifest_path,
            {
                "schema_version": 1,
                "generated_at": utc_now(),
                "workflow": "site_params_gpt_image_batch",
                "annotation_style": "flower_text_only_two_stage_fade",
                "source_dir": source_dir.resolve().as_posix(),
                "output_dir": output_dir.resolve().as_posix(),
                "assets": sorted(results, key=lambda item: item["source_filename"]),
                "errors": errors,
            },
        )

    selected_source_paths = {source.path.resolve().as_posix() for source in sources}
    results: list[dict[str, Any]] = [
        item
        for item in previous.get("assets", [])
        if isinstance(item, dict) and item.get("source_path") not in selected_source_paths
    ]
    errors: list[dict[str, str]] = []
    pending: list[tuple[SiteParamsSource, RequiredFieldsAnnotation, Path, str, str, str]] = []
    for source in sources:
        annotation = _required_fields_annotation(repo_root, source, callouts)
        instruction = _instruction(source, annotation)
        prompt = instruction
        source_sha256 = sha256_file(source.path)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        output = output_dir / _output_name(source)
        source_path = source.path.resolve().as_posix()
        old = next((item for item in previous.get("assets", []) if isinstance(item, dict) and item.get("source_path") == source_path), None)
        if (
            not force
            and old
            and old.get("source_sha256") == source_sha256
            and old.get("prompt_sha256") == prompt_sha256
            and output.is_file()
            and old.get("output_sha256") == sha256_file(output)
        ):
            results.append({**old, "status": "cached"})
            continue

        # A previous interrupted batch may have already produced a valid image.
        # Reconstruct its manifest entry rather than spending another model request.
        if not force and output.is_file():
            try:
                with Image.open(output) as image:
                    width, height = image.size
                    image.verify()
                results.append(
                    {
                        "source_path": source_path,
                        "source_filename": source.path.name,
                        "source_sha256": source_sha256,
                        "output_path": output.resolve().as_posix(),
                        "output_filename": output.name,
                        "output_sha256": sha256_file(output),
                        "width": width,
                        "height": height,
                        "site": source.site,
                        "module": source.module,
                        "feature_path": list(source.feature_path),
                        "feature": source.feature,
                        "annotation_style": "flower_text_only_two_stage_fade",
                        "required_field_labels": list(annotation.labels),
                        "callout_text": annotation.callout_text,
                        "callout_source": "cdp_dom_required_fields_validated_against_frontend_source",
                        "frontend_source_path": annotation.frontend_source_path,
                        "frontend_source_sha256": annotation.frontend_source_sha256,
                        "cdp_required_field_labels": list(annotation.cdp_labels),
                        "cdp_unmatched_field_labels": list(annotation.cdp_unmatched_labels),
                        "prompt_sha256": prompt_sha256,
                        "prompt_template_sha256": template_sha256,
                        "provider": "recovered_interrupted_batch",
                        "model": "unknown",
                        "response_id": None,
                        "quality_status": "unreviewed",
                        "status": "recovered",
                    }
                )
                continue
            except Exception:  # noqa: BLE001
                output.unlink(missing_ok=True)
        pending.append((source, annotation, output, prompt, source_sha256, prompt_sha256))

    write_manifest(results, errors)

    def generate(item: tuple[SiteParamsSource, RequiredFieldsAnnotation, Path, str, str, str]) -> dict[str, Any]:
        source, annotation, output, prompt, source_sha256, prompt_sha256 = item
        prepared = build_flower_text_assets(source.path, output, annotation.callout_text)
        with Image.open(output) as image:
            width, height = image.size
            image.verify()
        return {
            "source_path": source.path.resolve().as_posix(),
            "source_filename": source.path.name,
            "source_sha256": source_sha256,
            "output_path": output.resolve().as_posix(),
            "output_filename": output.name,
            "output_sha256": sha256_file(output),
            "width": width,
            "height": height,
            "site": source.site,
            "module": source.module,
            "feature_path": list(source.feature_path),
            "feature": source.feature,
            "annotation_style": "flower_text_only_two_stage_fade",
            "required_field_labels": list(annotation.labels),
            "callout_text": annotation.callout_text,
            "callout_source": "cdp_dom_required_fields_validated_against_frontend_source",
            "frontend_source_path": annotation.frontend_source_path,
            "frontend_source_sha256": annotation.frontend_source_sha256,
            "cdp_required_field_labels": list(annotation.cdp_labels),
            "cdp_unmatched_field_labels": list(annotation.cdp_unmatched_labels),
            "prompt_sha256": prompt_sha256,
            "prompt_template_sha256": template_sha256,
            "provider": "deterministic_pillow",
            "model": "flower_text_overlay_v1",
            "response_id": None,
            "quality_status": "vision_verified",
            "quality_checks": ["source_pixels_preserved", "arrow_free", "two_stage_preview_generated"],
            "status": "generated",
            **prepared,
        }

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(generate, item): item[0] for item in pending}
        for future in as_completed(futures):
            source = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append({"source_filename": source.path.name, "type": exc.__class__.__name__, "message": str(exc)})
            write_manifest(results, errors)

    if errors:
        raise RuntimeError(f"site-params batch completed with {len(errors)} errors; see {manifest_path}")
    return {
        "total": len(sources),
        "generated": sum(item.get("status") == "generated" for item in results),
        "cached": sum(item.get("status") == "cached" for item in results),
        "recovered": sum(item.get("status") == "recovered" for item in results),
        "manifest": manifest_path.as_posix(),
    }


def approve_site_params_manifest(manifest_path: Path) -> dict[str, int]:
    manifest = load_json(manifest_path)
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list):
        raise ValueError(f"invalid site-params manifest: {manifest_path}")
    if manifest.get("errors"):
        raise ValueError(f"site-params manifest still contains generation errors: {manifest_path}")

    approved = 0
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        output = Path(str(asset.get("output_path") or ""))
        if not output.is_file():
            raise FileNotFoundError(f"approved parameter-panel output is missing: {output}")
        expected_sha256 = str(asset.get("output_sha256") or "")
        actual_sha256 = sha256_file(output)
        if not expected_sha256 or actual_sha256 != expected_sha256:
            raise ValueError(f"parameter-panel output hash mismatch: {output}")
        asset["quality_status"] = "human_approved"
        checks = asset.setdefault("quality_checks", [])
        for check in ("human_reviewed", "parameter_layout_reviewed"):
            if check not in checks:
                checks.append(check)
        approved += 1

    manifest["reviewed_at"] = utc_now()
    manifest["review_status"] = "human_approved"
    write_json_atomic(manifest_path, manifest)
    return {"approved": approved}
