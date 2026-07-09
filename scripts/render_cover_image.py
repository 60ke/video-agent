from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_gpt_image_keyframes import DEFAULT_CONFIG, dry_run_config, gpt_edit_image, load_config

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
SAFE_TOP = 240
SAFE_BOTTOM = 1680
SAFE_HEIGHT = 1440


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else case_dir / path


def as_case_relative(case_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(case_dir.resolve(strict=False)).as_posix()


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in project.get("assets", []) if isinstance(asset, dict) and asset.get("id")}


def load_cover_plan(path: Path) -> dict[str, Any]:
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        raise ValueError(f"cover plan JSON is invalid: {path}")
    plan = payload.get("cover_plan", payload)
    if not isinstance(plan, dict):
        raise ValueError(f"cover_plan is invalid: {path}")
    title = str(plan.get("title") or "").strip()
    if not title:
        raise ValueError("cover_plan.title is required")
    return plan


def load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def draw_centered_text(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.ImageFont, *, fill: tuple[int, int, int] = (255, 255, 255), stroke_width: int = 0, stroke_fill: tuple[int, int, int] = (0, 0, 0)) -> int:
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=10, stroke_width=stroke_width)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = (TARGET_WIDTH - width) // 2
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=10, align="center", stroke_width=stroke_width, stroke_fill=stroke_fill)
    return y + height


def wrap_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    return "\n".join(chunks[:3])


def project_from_plan(plan: dict[str, Any], case_dir: Path) -> dict[str, Any]:
    source_project = str(plan.get("source_project") or "")
    path = resolve_case_path(case_dir, source_project)
    if path and path.is_file():
        payload = load_json(path, {})
        if isinstance(payload, dict):
            return payload
    for fallback in (case_dir / "video_project.effects.json", case_dir / "video_project.json"):
        payload = load_json(fallback, {})
        if isinstance(payload, dict) and payload:
            return payload
    return {}


def reference_paths(case_dir: Path, project: dict[str, Any], plan: dict[str, Any]) -> list[tuple[str, Path, dict[str, Any]]]:
    assets = asset_index(project)
    result: list[tuple[str, Path, dict[str, Any]]] = []
    for idx, asset_id in enumerate(plan.get("reference_asset_ids", [])):
        asset = assets.get(str(asset_id), {})
        source = str(asset.get("source") or asset.get("relative_source") or "")
        path = resolve_case_path(case_dir, source)
        if path and path.is_file():
            label = f"Image {chr(ord('A') + idx)}"
            result.append((label, path, asset))
    return result


def fit_thumb(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGB")
    return ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)


def make_reference_sheet(case_dir: Path, refs: list[tuple[str, Path, dict[str, Any]]], output_path: Path) -> Path:
    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (245, 247, 252))
    bg = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (210, 225, 255)).filter(ImageFilter.GaussianBlur(18))
    canvas = Image.blend(canvas, bg, 0.25)
    draw = ImageDraw.Draw(canvas)
    label_font = load_font(30, bold=True)
    draw.rectangle((0, SAFE_TOP, TARGET_WIDTH - 1, SAFE_BOTTOM), outline=(80, 150, 255), width=3)
    draw.text((32, 28), "Reference sheet for cover generation", font=load_font(34, bold=True), fill=(30, 40, 70))
    draw.text((32, 76), "Final cover must keep key content inside the blue 3:4 center area.", font=load_font(24), fill=(70, 82, 110))
    if not refs:
        draw_centered_text(draw, "No reference image provided", 840, load_font(52, bold=True), fill=(40, 50, 80))
    card_w = 940
    card_h = 410 if len(refs) >= 3 else 500
    y = 190
    for label, path, asset in refs[:3]:
        x = (TARGET_WIDTH - card_w) // 2
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=28, fill=(255, 255, 255), outline=(215, 225, 245), width=2)
        thumb = fit_thumb(path, (card_w - 70, card_h - 105))
        canvas.paste(thumb, (x + (card_w - thumb.width) // 2, y + 66))
        purpose = str(asset.get("role") or asset.get("description") or "reference")[:40]
        draw.text((x + 28, y + 22), f"{label}: {purpose}", font=label_font, fill=(30, 55, 120))
        y += card_h + 34
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return output_path


def cover_prompt(plan: dict[str, Any], refs: list[tuple[str, Path, dict[str, Any]]]) -> str:
    title = str(plan.get("title") or "").strip()
    subtitle = str(plan.get("subtitle") or "").strip()
    summary = str(plan.get("summary") or "").strip()
    layout = str(plan.get("layout_type") or "result_with_small_ui")
    style = str(plan.get("style_hint") or "short_video_feature_seed")
    ref_lines = []
    for idx, (label, _path, asset) in enumerate(refs[:3]):
        purpose = "primary visual" if idx == 0 else "supporting visual"
        desc = str(asset.get("description") or asset.get("role") or "").strip()
        ref_lines.append(f"{label}: use as {purpose}. {desc}".strip())
    ref_text = "\n".join(ref_lines) if ref_lines else "No reference image is available; create a clean abstract product-demo cover without inventing factual UI details."
    return f"""
Create a high-quality vertical short-video cover image, final canvas 1080x1920.

STRICT TITLE REQUIREMENT:
Render the main title exactly as this text, character by character: "{title}"
Do not rewrite it, omit any character, translate it, replace it with synonyms, or create garbled text.

CENTRAL 3:4 SAFE-ZONE REQUIREMENT:
Short-video platforms will crop the final vertical cover to the central 3:4 region. Put all key information inside the central safe zone: x=0..1080, y=240..1680.
The main title, the main subject/result image, any person/product subject, and the supporting subtitle must all stay inside that safe zone.
Outside the safe zone, use only background extension, glow, gradients, outlines, blur, and decoration. Do not place any key text, logo, result, person face, product subject, or important UI outside the safe zone.

CONTENT:
Video topic summary: {summary}
Supporting subtitle text: "{subtitle}"
Layout type: {layout}
Style hint: {style}

REFERENCE ROLES:
{ref_text}

DESIGN DIRECTION:
Make the cover readable on mobile feeds, with strong contrast, clear hierarchy, and a product-demo / feature-seeding look. Prefer a result-image hero composition. If a website UI reference is included, use it only as a small supporting card or subtle context, not as the main subject. Do not invent unrelated UI, brands, products, or generated results. Use the uploaded reference sheet only as source material and visual context.
""".strip()


def normalize_canvas(input_path: Path, output_path: Path) -> dict[str, Any]:
    image = Image.open(input_path).convert("RGB")
    fitted = ImageOps.fit(image, (TARGET_WIDTH, TARGET_HEIGHT), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fitted.save(output_path, "PNG")
    return probe_image(output_path)


def crop_preview(input_path: Path, output_path: Path) -> dict[str, Any]:
    image = Image.open(input_path).convert("RGB")
    if image.size != (TARGET_WIDTH, TARGET_HEIGHT):
        image = ImageOps.fit(image, (TARGET_WIDTH, TARGET_HEIGHT), method=Image.Resampling.LANCZOS)
    crop = image.crop((0, SAFE_TOP, TARGET_WIDTH, SAFE_BOTTOM))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output_path, "PNG")
    return probe_image(output_path)


def probe_image(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
    return {
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 6) if height else None,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def dry_run_cover(plan: dict[str, Any], refs: list[tuple[str, Path, dict[str, Any]]], output_path: Path) -> dict[str, Any]:
    canvas = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (22, 31, 60))
    bg = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (56, 104, 210)).filter(ImageFilter.GaussianBlur(24))
    canvas = Image.blend(canvas, bg, 0.42)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, TARGET_WIDTH, SAFE_TOP), fill=(20, 28, 55))
    draw.rectangle((0, SAFE_BOTTOM, TARGET_WIDTH, TARGET_HEIGHT), fill=(20, 28, 55))
    draw.rounded_rectangle((44, SAFE_TOP + 36, TARGET_WIDTH - 44, SAFE_BOTTOM - 36), radius=42, outline=(130, 210, 255), width=4)
    if refs:
        thumb = fit_thumb(refs[0][1], (860, 760))
        x = (TARGET_WIDTH - thumb.width) // 2
        y = SAFE_TOP + 470
        draw.rounded_rectangle((x - 20, y - 20, x + thumb.width + 20, y + thumb.height + 20), radius=34, fill=(255, 255, 255))
        canvas.paste(thumb, (x, y))
    title = wrap_text(str(plan.get("title") or ""), 12)
    subtitle = wrap_text(str(plan.get("subtitle") or ""), 18)
    draw_centered_text(draw, title, SAFE_TOP + 84, load_font(76, bold=True), fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 12, 48))
    if subtitle:
        draw_centered_text(draw, subtitle, SAFE_BOTTOM - 190, load_font(44, bold=True), fill=(225, 245, 255), stroke_width=2, stroke_fill=(0, 20, 60))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return probe_image(output_path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    plan_path = Path(args.plan).expanduser().resolve(strict=False) if args.plan else case_dir / "output" / "cover" / "cover_plan.json"
    plan = load_cover_plan(plan_path)
    project = project_from_plan(plan, case_dir)
    refs = reference_paths(case_dir, project, plan)
    output_dir = case_dir / "output" / "cover"
    reference_sheet = make_reference_sheet(case_dir, refs, output_dir / "cover_reference_sheet.png")
    output_path = Path(args.output).expanduser().resolve(strict=False) if args.output else output_dir / "cover_main.png"
    raw_output = output_dir / "cover_main.raw.png"
    prompt = cover_prompt(plan, refs)
    if args.dry_run:
        metadata = dry_run_cover(plan, refs, output_path)
        provider = "dry_run_pillow"
    else:
        config_path = Path(args.config).expanduser().resolve(strict=False) if args.config else DEFAULT_CONFIG
        config = dry_run_config() if args.dry_run else load_config(config_path)
        gpt_edit_image(config, reference_sheet, prompt, raw_output)
        metadata = normalize_canvas(raw_output, output_path)
        provider = config.model
    preview_path = output_dir / "cover_main_3x4_crop_preview.png"
    preview_metadata = crop_preview(output_path, preview_path)
    report_path = case_dir / "output" / "reports" / "cover_generation_report.json"
    report = {
        "schema_version": 1,
        "ok": True,
        "provider": provider,
        "cover": as_case_relative(case_dir, output_path),
        "crop_preview": as_case_relative(case_dir, preview_path),
        "reference_sheet": as_case_relative(case_dir, reference_sheet),
        "plan": str(plan_path),
        "title": plan.get("title"),
        "safe_zone": plan.get("safe_zone"),
        "metadata": metadata,
        "crop_preview_metadata": preview_metadata,
        "reference_asset_ids": plan.get("reference_asset_ids", []),
        "qa_required": [
            "Check title exactly matches cover.title.",
            "Check all key content remains inside central 3:4 crop preview.",
            "Check no key information appears outside the safe zone.",
        ],
        "prompt": prompt,
    }
    write_json(report_path, report)
    return {"ok": True, "code": "ok", "reason": "", "data": {"cover": str(output_path), "crop_preview": str(preview_path), "reference_sheet": str(reference_sheet), "report": str(report_path)}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a short-video cover image from a cover plan and reference assets.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--plan", help="Defaults to output/cover/cover_plan.json")
    parser.add_argument("--config", help="GPT image config path. Defaults to config/gpt_image.local.json.")
    parser.add_argument("--output", help="Defaults to output/cover/cover_main.png")
    parser.add_argument("--dry-run", action="store_true", help="Render a local Pillow cover for layout validation instead of calling GPT Image.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Cover image: {output['data']['cover']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
