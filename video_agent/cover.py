from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import Field

from video_agent.ai.gpt_image import edit_image
from video_agent.contracts.base import Contract
from video_agent.io import load_json, load_model, sha256_file, utc_now, write_json_atomic
from video_agent.contracts import AssetCatalog, RenderPlan, VisualPlan


class CoverSpec(Contract):
    title: str = Field(min_length=1, max_length=28)
    subtitle_hint: str | None = Field(default=None, max_length=40)
    narration_text: str | None = Field(default=None, max_length=10000)
    style_hint: str = "short_video_feature_seed"
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=3)
    max_references: int = Field(default=3, ge=1, le=3)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (Path("C:/Windows/Fonts/msyhbd.ttc"), Path("C:/Windows/Fonts/simhei.ttf")):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _probe(path: Path) -> dict[str, Any]:
    result = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], path.parent)
    if result.returncode:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-2000:]}")
    return json.loads(result.stdout)


def _frame_count(path: Path) -> int:
    probe = _probe(path)
    stream = next(item for item in probe["streams"] if item.get("codec_type") == "video")
    if stream.get("nb_frames") and str(stream["nb_frames"]).isdigit():
        return int(stream["nb_frames"])
    rate_num, rate_den = (int(part) for part in str(stream["avg_frame_rate"]).split("/"))
    duration = float((probe.get("format") or {}).get("duration") or 0)
    return round(duration * rate_num / rate_den)


def _select_references(repo_root: Path, spec: CoverSpec, catalog: AssetCatalog, visual: VisualPlan) -> list[Path]:
    assets = {asset.asset_id: asset for asset in catalog.assets}
    usage = Counter(asset_id for shot in visual.shots for asset_id in shot.asset_ids)
    selected: list[str] = []
    for asset_id in spec.reference_asset_ids:
        asset = assets.get(asset_id)
        if not asset or asset.media_type != "image" or not asset.production_eligible:
            raise ValueError(f"cover reference is not an eligible image: {asset_id}")
        selected.append(asset_id)
    candidates = [
        asset
        for asset in assets.values()
        if asset.media_type == "image"
        and asset.production_eligible
        and asset.quality.status in {"machine_checked", "vision_verified", "human_approved"}
        and asset.asset_id in usage
        and asset.asset_id not in selected
    ]
    candidates.sort(
        key=lambda asset: (
            asset.role != "result_image",
            -usage[asset.asset_id],
            asset.evidence_class.value not in {"E0_source_evidence", "E1_faithful_derivative"},
            asset.filename,
        )
    )
    selected.extend(asset.asset_id for asset in candidates[: max(0, spec.max_references - len(selected))])
    if not selected:
        raise ValueError("cover requires at least one eligible image used by the video")
    return [(repo_root / assets[asset_id].path).resolve() for asset_id in selected[: spec.max_references]]


def _reference_sheet(paths: list[Path], output: Path) -> Path:
    canvas = Image.new("RGB", (1024, 1024), (10, 14, 20))
    draw = ImageDraw.Draw(canvas)
    boxes = [(32, 32, 992, 992)] if len(paths) == 1 else [(32, 32, 992, 500), (32, 524, 992, 992)]
    if len(paths) == 3:
        boxes = [(32, 32, 992, 490), (32, 514, 500, 992), (524, 514, 992, 992)]
    for index, (path, box) in enumerate(zip(paths, boxes)):
        with Image.open(path) as source:
            fitted = ImageOps.contain(source.convert("RGB"), (box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
        x = box[0] + (box[2] - box[0] - fitted.width) // 2
        y = box[1] + (box[3] - box[1] - fitted.height) // 2
        canvas.paste(fitted, (x, y))
        draw.ellipse((box[0] + 12, box[1] + 12, box[0] + 62, box[1] + 62), fill=(255, 62, 42))
        draw.text((box[0] + 29, box[1] + 19), chr(ord("A") + index), font=_font(24), fill="white", anchor="mm")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)
    return output


def _prompt(spec: CoverSpec, reference_count: int, narration_text: str = "") -> str:
    subtitle = spec.subtitle_hint or ""
    narration_context = narration_text or "（未提供口播文案）"
    return f"""
Create a high-quality vertical short-video cover image, final canvas 1080x1920.

STRICT TITLE REQUIREMENT:
Render the main title exactly, character by character, as: "{spec.title}"
Do not rewrite, omit, translate, replace, or garble any character. The only other new text allowed is the optional subtitle: "{subtitle}". If the optional subtitle is empty, render no subtitle.

FULL NARRATION CONTEXT:
{narration_context}

Use the full narration only to understand the video's subject, hook, audience, and visual priority. Do not render the narration as subtitles, a transcript, a paragraph, or multiple caption lines. The cover is a thumbnail, not a video subtitle frame.

CENTRAL 3:4 SAFE ZONE:
Put the title, subtitle, main result subject, logo, and every important element inside x=0..1080, y=240..1680. Keep the most critical content inside x=100..860, y=240..1500 so Douyin controls and metadata cannot cover it. Outside the central safe zone use only background extension and restrained decoration.

REFERENCES:
The reference sheet contains {reference_count} approved images labelled A, B, C. Prefer a result image as the hero. Website UI may only be a small supporting element. Preserve the referenced design, product, brand, and result content; do not invent unrelated UI, brands, products, people, or generated results.

BRAND LOGO:
If any reference image is a brand logo (identified by its square aspect ratio and clean logomark), reproduce it pixel-faithfully in the cover. Do not redraw, restyle, recolor, simplify, or invent a different logo. Place the brand logo as a small badge in a corner or near the title, never as the main hero. The official brand logo in the references is the ONLY logo allowed on the cover.

DESIGN:
Mobile-feed readability, high contrast, strong hierarchy, lively but clean short-video feature-seeding composition. Style hint: {spec.style_hint}. Do not add extra marketing copy, watermarks, fake interface text, or decorative paragraphs.
""".strip()


def _normalize_cover(raw: Path, cover: Path, preview: Path) -> None:
    with Image.open(raw) as image:
        normalized = ImageOps.fit(image.convert("RGB"), (1080, 1920), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    cover.parent.mkdir(parents=True, exist_ok=True)
    normalized.save(cover, "PNG")
    normalized.crop((0, 240, 1080, 1680)).save(preview, "PNG")


def _prepend_one_frame(body: Path, cover: Path, output: Path, fps: int) -> None:
    duration = 1 / fps
    work = output.with_suffix(".cover_work.mp4")
    command = [
        "ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", str(cover), "-i", str(body),
        "-filter_complex",
        (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={fps},"
            f"trim=duration={duration:.9f},setpts=PTS-STARTPTS[cv];"
            f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.9f},asetpts=PTS-STARTPTS[ca];"
            f"[1:v]fps={fps},setpts=PTS-STARTPTS[bv];[1:a]aresample=48000,asetpts=PTS-STARTPTS[ba];"
            "[cv][ca][bv][ba]concat=n=2:v=1:a=1[v][a]"
        ),
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(work),
    ]
    result = _run(command, output.parent)
    if result.returncode:
        raise RuntimeError(f"cover prepend failed: {result.stderr[-4000:]}")
    shutil.move(work, output)


def _extract_frame(video: Path, frame: int, output: Path) -> None:
    result = _run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1", "-vsync", "vfr", str(output)],
        video.parent,
    )
    if result.returncode:
        raise RuntimeError(f"cover frame extraction failed: {result.stderr[-1000:]}")


def _image_mae(left: Path, right: Path) -> float:
    with Image.open(left) as left_image, Image.open(right) as right_image:
        a = np.asarray(ImageOps.fit(left_image.convert("RGB"), (1080, 1920), Image.Resampling.LANCZOS), dtype=np.float32)
        b = np.asarray(ImageOps.fit(right_image.convert("RGB"), (1080, 1920), Image.Resampling.LANCZOS), dtype=np.float32)
    return float(np.abs(a - b).mean())


def postprocess_cover(repo_root: Path, case_dir: Path, run_dir: Path, spec_path: Path) -> dict[str, Any]:
    spec = load_model(spec_path, CoverSpec)
    video = run_dir / "final" / "video.mp4"
    if not video.is_file():
        raise FileNotFoundError(f"rendered video is missing: {video}")
    catalog = load_model(run_dir / "asset_catalog.json", AssetCatalog)
    visual = load_model(run_dir / "visual_plan.json", VisualPlan)
    plan = load_model(run_dir / "render_plan.json", RenderPlan)
    work = run_dir / "work" / "cover"
    final = run_dir / "final"
    report_path = run_dir / "cover_report.json"
    previous = load_json(report_path) if report_path.is_file() else {}
    body = work / "video_without_cover.mp4"
    current_sha = sha256_file(video)
    if previous.get("output_video_sha256") == current_sha and body.is_file():
        pass
    else:
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, body)

    references = _select_references(repo_root, spec, catalog, visual)
    sheet = _reference_sheet(references, work / "cover_reference_sheet.png")
    narration_text = spec.narration_text
    narration_path = run_dir / "narration.json"
    if not narration_text and narration_path.is_file():
        narration_data = load_json(narration_path)
        beats = narration_data.get("beats", []) if isinstance(narration_data, dict) else []
        narration_text = " ".join(
            str(beat.get("spoken_text") or "")
            for beat in beats
            if isinstance(beat, dict) and beat.get("spoken_text")
        )
    prompt = _prompt(spec, len(references), narration_text or "")
    result = edit_image(repo_root, sheet, prompt)
    raw = work / "cover_raw.png"
    raw.write_bytes(result.content)
    cover = final / "cover.png"
    preview = final / "cover_3x4_preview.png"
    _normalize_cover(raw, cover, preview)
    body_frames = _frame_count(body)
    _prepend_one_frame(body, cover, video, plan.fps)
    output_frames = _frame_count(video)
    if output_frames != body_frames + 1:
        raise ValueError(f"cover postprocess must add exactly one frame: {body_frames}->{output_frames}")
    encoded_cover = work / "encoded_cover_frame.png"
    encoded_body_first = work / "encoded_body_first.png"
    shifted_body_first = work / "shifted_body_first.png"
    _extract_frame(video, 0, encoded_cover)
    _extract_frame(body, 0, encoded_body_first)
    _extract_frame(video, 1, shifted_body_first)
    cover_mae = _image_mae(cover, encoded_cover)
    shifted_body_mae = _image_mae(encoded_body_first, shifted_body_first)
    if cover_mae > 12.0 or shifted_body_mae > 12.0:
        raise ValueError(f"cover frame verification failed: cover_mae={cover_mae:.3f}, shifted_body_mae={shifted_body_mae:.3f}")
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "title": spec.title,
        "subtitle": spec.subtitle_hint,
        "cover": cover.as_posix(),
        "crop_preview": preview.as_posix(),
        "reference_sheet": sheet.as_posix(),
        "reference_paths": [path.as_posix() for path in references],
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "provider": result.provider,
        "model": result.model,
        "response_id": result.response_id,
        "fps": plan.fps,
        "cover_frames": 1,
        "body_frame_count": body_frames,
        "output_frame_count": output_frames,
        "body_video_sha256": sha256_file(body),
        "output_video_sha256": sha256_file(video),
        "cover_sha256": sha256_file(cover),
        "frame_verification": {"cover_mae": round(cover_mae, 3), "shifted_body_mae": round(shifted_body_mae, 3)},
        "checks": [
            "cover_1080x1920",
            "central_3x4_preview",
            "exactly_one_frame_prepended",
            "first_frame_matches_cover",
            "body_first_frame_shifted_to_frame_one",
            "body_audio_video_shifted_together",
        ],
    }
    write_json_atomic(report_path, report)
    return report
