from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_agent.io import load_json, sha256_file


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
        f"文件名解析路径是 {source.site} -> {source.module} -> {hierarchy}，当前功能为“{source.feature}”。"
        f"新增花字只能逐字写为“{annotation.callout_text}”，它是唯一允许新增的中文文字，且花字不得包含 * 或 ＊。"
        f"箭头指向这些字段所在区域：{', '.join(annotation.labels)}。字段名称只用于理解目标，不得额外写入画面。"
        "页面原有 UI 中已经存在的红色 * 或 ＊ 是界面内容，必须逐个原样保留；不得删除、隐藏、移动、改色、改样式、复制或用花字替换。"
        "绝不可把提示词、校验过程或来源说明渲染进图片，包括“已验证必填字段”“必填字段”“字段说明”“CDP”“前端源码”。"
        "花字和箭头应由 GPT Image 自然整合到原始参数面板，优先落在面板右侧或右下区域；不得新增右侧黑栏、左右分栏、空白区或缩小原始参数面板。"
        "原始参数面板必须从左至右铺满有效画面宽度，两侧外边距各不超过 3%；绝不可在右侧留下空白条、黑色空区或独立侧栏。"
        "花字可以覆盖普通表单内容或页面背景，唯一禁止遮挡的是原始页面标题或分区标题。"
        "不要使用程序化红框、规则矩形、圆圈、鼠标、人物头像或单独的动画图层。"
    )
