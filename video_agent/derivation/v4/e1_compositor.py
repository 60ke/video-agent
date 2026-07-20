from __future__ import annotations

import json
import platform
from hashlib import sha256
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from video_agent.media import CANVAS_SIZE, fit_canvas, stage_frame


_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simkai.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)


def load_chinese_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def fit_to_douyin_canvas(source: Path, output: Path) -> None:
    """Pixel-preserving 9:16 reframe used by site_faithful_reframe."""
    content = source.read_bytes()
    frame = fit_canvas(content)
    frame.save(output, format="PNG")


def _parse_callout_boxes(description: str | None) -> list[dict]:
    if not description:
        return []
    text = description.strip()
    if not text.startswith("{"):
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get("callouts") or payload.get("registered_callouts") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _default_menu_box(target_label: str, width: int, height: int) -> tuple[int, int, int, int]:
    digest = sha256(target_label.encode("utf-8")).digest()
    # Left navigation hover menu zone — stable per label, not OCR.
    left = int(width * 0.08)
    right = int(width * 0.42)
    top = int(height * (0.22 + (digest[0] % 40) / 100.0))
    box_h = max(48, int(height * 0.06))
    return left, top, right, min(height - 40, top + box_h)


def apply_feature_entry_callout(
    source: Path,
    output: Path,
    *,
    target_label: str,
    description: str | None = None,
) -> None:
    """Overlay a persisted or deterministic red double-ellipse callout (E1)."""
    content = source.read_bytes()
    frame = fit_canvas(content)
    draw = ImageDraw.Draw(frame)
    width, height = frame.size
    boxes = _parse_callout_boxes(description)
    chosen = None
    for item in boxes:
        label = str(item.get("target_label") or item.get("label") or "").strip()
        if label and target_label and label != target_label:
            continue
        box = item.get("box") or item.get("rect")
        if isinstance(box, dict) and {"x", "y", "w", "h"} <= set(box):
            x0 = int(float(box["x"]) * width)
            y0 = int(float(box["y"]) * height)
            x1 = int((float(box["x"]) + float(box["w"])) * width)
            y1 = int((float(box["y"]) + float(box["h"])) * height)
            chosen = (x0, y0, x1, y1)
            break
    if chosen is None:
        chosen = _default_menu_box(target_label or "功能", width, height)
    x0, y0, x1, y1 = chosen
    pad = 18
    outer = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    inner = (x0 - pad + 6, y0 - pad + 6, x1 + pad - 6, y1 + pad - 6)
    draw.ellipse(outer, outline=(220, 40, 40), width=6)
    draw.ellipse(inner, outline=(255, 90, 90), width=3)
    frame.save(output, format="PNG")


def _callout_text(fields: list[str]) -> str:
    labels = [field.strip() for field in fields if field.strip()]
    if not labels:
        return "填写必填项"
    if len(labels) > 3:
        return "填写必填项"
    return "+".join(labels)


def _draw_flower_text(base: Image.Image, callout_text: str) -> Image.Image:
    """Deterministic hand-drawn-style calligraphy overlay (E1, no GPT)."""
    image = base.copy()
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_chinese_font(size=max(54, image.width // 14))
    text = callout_text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (image.width - text_w) // 2
    y = int(image.height * 0.72) - text_h // 2
    # Soft shadow + ink stroke for a scribbly readable hit.
    for dx, dy in ((3, 3), (-2, 2), (2, -1), (0, 0)):
        draw.text(
            (x + dx, y + dy),
            text,
            font=font,
            fill=(20, 20, 20, 90) if (dx, dy) != (0, 0) else (255, 70, 70, 235),
            stroke_width=2 if (dx, dy) == (0, 0) else 0,
            stroke_fill=(255, 255, 255, 180),
        )
    # Small accent dots (breathing marks), deterministic from text hash.
    digest = sha256(text.encode("utf-8")).digest()
    for index in range(3):
        cx = x + (digest[index] % max(text_w, 1))
        cy = y - 18 - (digest[index + 3] % 24)
        r = 4 + digest[index + 6] % 5
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 90, 90, 200))
    composed = Image.alpha_composite(image.convert("RGBA"), overlay)
    return composed.convert("RGB")


def render_parameter_flower_frames(
    source: Path,
    *,
    callout_fields: list[str],
    output_base: Path,
    output_stage: Path,
    output_final: Path,
) -> dict[str, str]:
    """
    Produce base/stage/final for site_params_flower_text_frame_sequence.

    base  = faithful 9:16 reframe (no flower)
    final = same pixels + deterministic flower calligraphy from callout_fields
    stage = registered difference blend between base and final
    """
    content = source.read_bytes()
    base = fit_canvas(content)
    base.save(output_base, format="PNG")
    callout = _callout_text(callout_fields)
    final = _draw_flower_text(base, callout)
    # Build a simple mask from absolute difference for mid-frame blend.
    base_arr = np.array(base.convert("RGB"), dtype=np.int16)
    final_arr = np.array(final.convert("RGB"), dtype=np.int16)
    delta = np.abs(final_arr - base_arr).max(axis=2)
    mask = np.where(delta > 12, 255, 0).astype(np.uint8)
    stage = stage_frame(base, final, mask, strength=0.55)
    stage.save(output_stage, format="PNG")
    final.save(output_final, format="PNG")
    return {
        "callout_text": callout,
        "platform": platform.system(),
        "model": "deterministic_flower_overlay_v1",
    }


def try_load_persisted_parameter_sequence(
    repo_root: Path,
    *,
    parent_sha256: str,
) -> dict[str, Path] | None:
    """Reuse previously generated offline parameter sequences when content hash matches."""
    manifest = repo_root / "assets" / "derived" / "sites" / "柯幻熊猫" / "文生图" / "参数面板序列" / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for item in payload.get("sequences", []):
        if not isinstance(item, dict):
            continue
        if item.get("source_sha256") != parent_sha256:
            continue
        frames = item.get("frames") or {}
        paths: dict[str, Path] = {}
        ok = True
        for key in ("base", "stage", "final"):
            frame = frames.get(key) if isinstance(frames, dict) else None
            if not isinstance(frame, dict) or not frame.get("path"):
                ok = False
                break
            path = Path(str(frame["path"]))
            if not path.is_file():
                # manifest may store absolute paths from another machine; try repo-relative
                rel = repo_root / Path(*path.parts[-6:])
                path = rel if rel.is_file() else path
            if not path.is_file():
                ok = False
                break
            paths[key] = path
        if ok:
            return paths
    return None


# Keep canvas constant import used by tests/callers.
assert CANVAS_SIZE == (1080, 1920)
