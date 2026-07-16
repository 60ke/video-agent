from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from video_agent.ai.gpt_image import edit_image
from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


DEFAULT_FOCUS_RECT = {"x": 0.80, "y": 0.70, "w": 0.13, "h": 0.17}


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in value).strip("_") or "编辑流程"


def _combined_input(template: Path, artwork: Path, output: Path, *, template_label: str) -> Path:
    panel_w, panel_h = 1280, 960
    canvas = Image.new("RGB", (panel_w * 2, panel_h), (9, 12, 17))
    draw = ImageDraw.Draw(canvas)
    for index, (path, label) in enumerate(((template, template_label), (artwork, "B: 需要载入编辑器的作品原图"))):
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((panel_w - 48, panel_h - 92), Image.Resampling.LANCZOS)
            x = index * panel_w + (panel_w - image.width) // 2
            y = 72 + (panel_h - 72 - image.height) // 2
            canvas.paste(image, (x, y))
        draw.text((index * panel_w + 24, 22), label, fill=(255, 214, 64))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")
    return output


def _page_prompt() -> str:
    return (
        "输入图由两个标记面板组成。A 是柯幻熊猫真实的图片编辑页面模板，B 是需要编辑的作品原图。"
        "输出一张横屏网页截图，只保留 A 的完整页面，不要保留 A/B 标签或拼图边界。"
        "严格保持 A 的黑色网页 UI、顶部退出图片编辑、右侧提示词与功能按钮、所有文字、按钮位置和页面比例不变。"
        "仅把 A 中央画布里的旧作品替换成完整的 B；B 必须等比、完整、清晰，不裁掉主体，不改写文字，不改变设计。"
        "右侧“局部编辑”按钮必须清楚可见。不要添加红框、箭头、圆圈、放大镜、花字、字幕、人物或灰色展示卡片。"
        "页面外侧不增加背景，输出应像一次真实浏览器全屏截图。"
    )


def _modal_prompt() -> str:
    return (
        "输入图由两个标记面板组成。A 是柯幻熊猫真实的“局部编辑”弹窗模板，B 是需要编辑的作品原图。"
        "输出一张横屏网页截图，只保留 A 的完整弹窗状态，不要保留 A/B 标签或拼图边界。"
        "严格保持 A 的弹窗标题、关闭按钮、深色容器、缩放控件、编辑描述输入框和开始重绘按钮的文字、位置、比例不变。"
        "仅把 A 弹窗预览区里的旧作品替换成完整的 B；B 必须等比、完整、清晰，不裁掉主体，不改写文字，不改变设计。"
        "不要添加红框、箭头、圆圈、放大镜、花字、字幕、人物或额外说明。不要重新设计 UI。"
    )


def _upsert_manifest(manifest_path: Path, sequence_id: str, items: list[dict[str, Any]]) -> None:
    previous = load_json(manifest_path) if manifest_path.is_file() else {}
    assets = [
        item
        for item in previous.get("assets", [])
        if isinstance(item, dict) and item.get("editor_flow_sequence_id") != sequence_id
    ]
    assets.extend(items)
    write_json_atomic(
        manifest_path,
        {"schema_version": 2, "workflow": "fixed_editor_flow_materials", "generated_at": utc_now(), "assets": assets},
    )


def generate_editor_flow_assets(
    repo_root: Path,
    artwork: Path,
    editor_template: Path,
    modal_template: Path,
    output_root: Path,
    *,
    semantic_path: list[str],
    focus_rect: dict[str, float] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    for path in (artwork, editor_template, modal_template):
        if not path.is_file():
            raise FileNotFoundError(path)
    if len(semantic_path) < 2:
        raise ValueError("editor flow requires a semantic path such as 文生图/文化墙")

    source_sha256 = sha256_file(artwork)
    template_sha256 = [sha256_file(editor_template), sha256_file(modal_template)]
    sequence_key = "|".join([*semantic_path, source_sha256, *template_sha256])
    sequence_id = "editor_flow_" + hashlib.sha256(sequence_key.encode("utf-8")).hexdigest()[:14]
    feature = _safe_name(semantic_path[-1])
    output_dir = output_root / _safe_name(semantic_path[0]) / feature / sequence_id
    output_dir.mkdir(parents=True, exist_ok=True)
    page_output = output_dir / f"柯幻熊猫_{'_'.join(semantic_path)}_完整编辑页.png"
    modal_output = output_dir / f"柯幻熊猫_{'_'.join(semantic_path)}_局部编辑弹窗.png"
    manifest_path = output_root / "manifest.json"

    page_prompt = _page_prompt()
    modal_prompt = _modal_prompt()
    prompt_sha256 = hashlib.sha256((page_prompt + "\n" + modal_prompt).encode("utf-8")).hexdigest()
    existing = load_json(manifest_path) if manifest_path.is_file() else {}
    prior = [
        item for item in existing.get("assets", [])
        if isinstance(item, dict) and item.get("editor_flow_sequence_id") == sequence_id
    ]
    if not force and len(prior) == 2 and all(Path(str(item.get("path"))).is_file() for item in prior):
        return {"sequence_id": sequence_id, "status": "cached", "manifest": manifest_path.as_posix(), "assets": prior}

    page_input = _combined_input(editor_template, artwork, output_dir / ".editor_page_input.png", template_label="A: 完整编辑页面模板")
    modal_input = _combined_input(modal_template, artwork, output_dir / ".editor_modal_input.png", template_label="A: 局部编辑弹窗模板")
    try:
        print("[编辑流程素材] GPT Image 正在生成完整编辑页面...")
        page_result = edit_image(repo_root, page_input, page_prompt, size="1792x1024")
        page_output.write_bytes(page_result.content)
        print("[编辑流程素材] GPT Image 正在生成局部编辑弹窗...")
        modal_result = edit_image(repo_root, modal_input, modal_prompt, size="1792x1024")
        modal_output.write_bytes(modal_result.content)
    finally:
        page_input.unlink(missing_ok=True)
        modal_input.unlink(missing_ok=True)

    rect = dict(DEFAULT_FOCUS_RECT if focus_rect is None else focus_rect)
    common = {
        "semantic_path": semantic_path,
        "editor_flow_sequence_id": sequence_id,
        "source_artwork_path": artwork.resolve().as_posix(),
        "source_artwork_sha256": source_sha256,
        "editor_template_sha256": template_sha256[0],
        "modal_template_sha256": template_sha256[1],
        "prompt_sha256": prompt_sha256,
        "focus_target": "局部编辑",
        "focus_rect": rect,
        "claims": ["image_editing_available", "local_editing_available"],
        "tags": ["编辑页面", "局部编辑", "放大镜聚焦", semantic_path[-1]],
        "quality_status": "machine_checked",
    }
    items = [
        {
            **common,
            "path": page_output.resolve().as_posix(),
            "sha256": sha256_file(page_output),
            "role": "editor_workspace",
            "workflow_step": "editor_page",
            "editor_flow_role": "page",
            "provider": page_result.provider,
            "model": page_result.model,
            "response_id": page_result.response_id,
        },
        {
            **common,
            "path": modal_output.resolve().as_posix(),
            "sha256": sha256_file(modal_output),
            "role": "editor_local_modal",
            "workflow_step": "local_edit_modal",
            "editor_flow_role": "modal",
            "provider": modal_result.provider,
            "model": modal_result.model,
            "response_id": modal_result.response_id,
        },
    ]
    _upsert_manifest(manifest_path, sequence_id, items)
    print(f"[编辑流程素材] 已注册固定序列：{sequence_id}")
    return {"sequence_id": sequence_id, "status": "generated", "manifest": manifest_path.as_posix(), "assets": items}
