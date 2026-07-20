from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Collection

import cv2
import numpy as np
from PIL import Image

from video_agent.ai.gpt_image import edit_image
from video_agent.media import CANVAS_SIZE, fit_canvas, stage_frame
from video_agent.assets.manifest_utils import without_legacy_review_fields
from video_agent.assets.site_params_batch import (
    IMAGE_SUFFIXES,
    SUFFIX,
    SiteParamsSource,
    _required_fields_annotation,
    parse_site_params_filename,
)
from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


def _prompt_base(source: SiteParamsSource) -> str:
    return (
        "编辑这张网站参数页截图，生成干净、可读的 9:16 参数页完整关键帧。"
        f"当前功能为“{source.feature}”。保留页面标题、全部表单、原有红色星号和开始生成按钮；"
        "将参数页放大到有效画面宽度，避免黑边、侧栏、留白和分屏。"
        "不要增加花字、箭头、红框、圆圈、鼠标、人物、贴纸或任何新文字。"
        "不要重写、删除或虚构原始 UI 文本。"
    )


def _prompt_final(source: SiteParamsSource, callout_text: str, labels: tuple[str, ...]) -> str:
    labels_text = "、".join(labels)
    return (
        "编辑这张干净的 9:16 参数页关键帧。保持页面构图、缩放、裁切、标题、表单、按钮和全部原有 UI 像素不变。"
        f"仅增加一组醒目的手绘花字“{callout_text}”，以有呼吸感的涂鸦笔触、描边和小装饰呈现，"
        f"表达填写这些必填字段：{labels_text}。花字不得包含 * 或 ＊，不得额外写出字段名或说明文字。"
        "花字可以覆盖普通表单或背景，但不得遮挡页面标题、分区标题、原有红色星号或开始生成按钮。"
        "不要添加箭头、连接线、红框、圆圈、鼠标、人物、头像或其他标记。"
        f"不要改变“{source.feature}”页面的任何 UI 内容。"
    )


def _fit_canvas(content: bytes) -> Image.Image:
    return fit_canvas(content)


def _register_final(base: Image.Image, final: Image.Image) -> tuple[Image.Image, np.ndarray, dict[str, Any]]:
    base_bgr = cv2.cvtColor(np.array(base.convert("RGB")), cv2.COLOR_RGB2BGR)
    final_bgr = cv2.cvtColor(np.array(final.convert("RGB")), cv2.COLOR_RGB2BGR)
    base_gray = cv2.cvtColor(base_bgr, cv2.COLOR_BGR2GRAY)
    final_gray = cv2.cvtColor(final_bgr, cv2.COLOR_BGR2GRAY)
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 120, 1e-6)
    method = "ecc_affine"
    try:
        score, warp = cv2.findTransformECC(base_gray, final_gray, warp, cv2.MOTION_AFFINE, criteria)
    except cv2.error:
        # Synthetic or very flat UI frames may not contain enough features for ECC.
        # They are already pixel-aligned because both frames use the canonical base canvas.
        score = 0.0
        method = "identity_fallback"
    translation = float(np.hypot(warp[0, 2], warp[1, 2]))
    scale_x = float(np.hypot(warp[0, 0], warp[1, 0]))
    scale_y = float(np.hypot(warp[0, 1], warp[1, 1]))
    if translation > 36 or not (0.94 <= scale_x <= 1.06 and 0.94 <= scale_y <= 1.06):
        raise ValueError("parameter sequence registration exceeds allowed transform")
    aligned_bgr = cv2.warpAffine(
        final_bgr,
        warp,
        CANVAS_SIZE,
        flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REPLICATE,
    )
    delta = cv2.absdiff(base_bgr, aligned_bgr)
    gray = cv2.cvtColor(delta, cv2.COLOR_BGR2GRAY)
    mask = cv2.threshold(gray, 24, 255, cv2.THRESH_BINARY)[1]
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8), iterations=1)
    mask = cv2.GaussianBlur(mask, (0, 0), 2.4)
    changed_ratio = float(np.count_nonzero(mask > 16) / mask.size)
    # GPT Image can adjust antialiasing, shadows, and local panel texture while
    # placing the flower text. Human approval remains the visual quality gate.
    if changed_ratio < 0.001 or changed_ratio > 0.40:
        raise ValueError(f"parameter sequence flower delta is implausible: {changed_ratio:.3f}")
    alpha = mask.astype(np.float32)[..., None] / 255.0
    composed = (base_bgr.astype(np.float32) * (1 - alpha) + aligned_bgr.astype(np.float32) * alpha).clip(0, 255).astype(np.uint8)
    return (
        Image.fromarray(cv2.cvtColor(composed, cv2.COLOR_BGR2RGB)),
        mask,
        {
            "method": method,
            "matrix": warp.tolist(),
            "ecc_score": float(score),
            "changed_ratio": changed_ratio,
            "status": "passed",
        },
    )


def _stage_frame(base: Image.Image, final: Image.Image, mask: np.ndarray, strength: float = 0.55) -> Image.Image:
    return stage_frame(base, final, mask, strength=strength)


def _frame_path(frames_dir: Path, source: SiteParamsSource, state: str) -> Path:
    stem = source.path.stem[: -len(SUFFIX)]
    names = {"base": "参数面板无花字图", "stage": "参数面板花字阶段图", "final": "参数面板花字完成图"}
    return frames_dir / f"{stem}_{names[state]}.png"


def _sequence_id(source: SiteParamsSource) -> str:
    return "params_" + "_".join(source.feature_path)


def generate_parameter_frame_sequences(
    repo_root: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    include: str | None = None,
    exclude: Collection[str] = (),
    workers: int = 1,
    force: bool = False,
) -> dict[str, Any]:
    paths = [
        path
        for path in sorted(source_dir.glob(f"*_文生图_*{SUFFIX}.*"))
        if path.suffix.lower() in IMAGE_SUFFIXES and (include is None or path.name == include) and path.name not in set(exclude)
    ]
    sources = [parse_site_params_filename(path) for path in paths]
    if not sources:
        raise FileNotFoundError("no parameter-panel screenshots match the requested selection")
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    previous = without_legacy_review_fields(load_json(manifest_path)) if manifest_path.is_file() else {}
    prior_by_source = {str(item.get("source_path")): item for item in previous.get("sequences", []) if isinstance(item, dict)}
    callouts = load_json(source_dir / "_callouts.json")

    def generate(source: SiteParamsSource) -> dict[str, Any]:
        annotation = _required_fields_annotation(repo_root, source, callouts)
        source_sha256 = sha256_file(source.path)
        base_prompt = _prompt_base(source)
        final_prompt = _prompt_final(source, annotation.callout_text, annotation.labels)
        prompt_sha256 = hashlib.sha256((base_prompt + "\n" + final_prompt).encode("utf-8")).hexdigest()
        paths = {state: _frame_path(frames_dir, source, state) for state in ("base", "stage", "final")}
        prior = prior_by_source.get(source.path.resolve().as_posix())
        if (
            not force
            and prior
            and prior.get("source_sha256") == source_sha256
            and prior.get("prompt_sha256") == prompt_sha256
            and all(path.is_file() for path in paths.values())
            and all(sha256_file(paths[state]) == prior.get("frames", {}).get(state, {}).get("sha256") for state in paths)
        ):
            return {**prior, "status": "cached"}
        base_edit = edit_image(repo_root, source.path, base_prompt)
        base = _fit_canvas(base_edit.content)
        base.save(paths["base"], format="PNG")
        final_edit = edit_image(repo_root, paths["base"], final_prompt)
        final_raw = _fit_canvas(final_edit.content)
        final, mask, registration = _register_final(base, final_raw)
        final.save(paths["final"], format="PNG")
        stage = _stage_frame(base, final, mask)
        stage.save(paths["stage"], format="PNG")
        frames = {
            "base": {
                "path": paths["base"].resolve().as_posix(), "sha256": sha256_file(paths["base"]),
                "origin": "gpt_image_edit", "provider": base_edit.provider, "model": base_edit.model,
                "response_id": base_edit.response_id,
            },
            "stage": {
                "path": paths["stage"].resolve().as_posix(), "sha256": sha256_file(paths["stage"]),
                "origin": "deterministic_frame_blend", "provider": "local", "model": "registered_difference_blend_v1",
                "stage_strength": 0.55,
            },
            "final": {
                "path": paths["final"].resolve().as_posix(), "sha256": sha256_file(paths["final"]),
                "origin": "gpt_image_edit", "provider": final_edit.provider, "model": final_edit.model,
                "response_id": final_edit.response_id,
            },
        }
        return {
            "sequence_id": _sequence_id(source), "site": source.site, "module": source.module,
            "feature_path": list(source.feature_path), "feature": source.feature,
            "source_path": source.path.resolve().as_posix(), "source_sha256": source_sha256,
            "required_field_labels": list(annotation.labels), "callout_text": annotation.callout_text,
            "frontend_source_path": annotation.frontend_source_path, "frontend_source_sha256": annotation.frontend_source_sha256,
            "cdp_required_field_labels": list(annotation.cdp_labels), "cdp_unmatched_field_labels": list(annotation.cdp_unmatched_labels),
            "prompt_sha256": prompt_sha256, "frames": frames, "registration": registration,
            "status": "generated",
        }

    selected_source_paths = {source.path.resolve().as_posix() for source in sources}
    results: list[dict[str, Any]] = [
        item
        for item in previous.get("sequences", [])
        if isinstance(item, dict) and item.get("source_path") not in selected_source_paths
    ]
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(generate, source): source for source in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append({"source_filename": source.path.name, "type": exc.__class__.__name__, "message": str(exc)})
            write_json_atomic(manifest_path, {"schema_version": 1, "workflow": "site_params_flower_text_frame_sequence", "generated_at": utc_now(), "sequences": sorted(results, key=lambda item: item["sequence_id"]), "errors": errors})
    if errors:
        raise RuntimeError(f"parameter sequence batch completed with {len(errors)} errors; see {manifest_path}")
    return {
        "total": len(sources),
        "generated": sum(item.get("status") == "generated" for item in results),
        "cached": sum(item.get("status") == "cached" for item in results),
        "manifest": manifest_path.as_posix(),
    }
