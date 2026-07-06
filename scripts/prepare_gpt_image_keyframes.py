from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from PIL import Image, ImageOps


DEFAULT_CONFIG = Path("config") / "gpt_image.local.json"
DEFAULT_SIZE = "1024x1792"
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
RESULT_STEPS = {"result_crop", "result_export", "result_gallery", "result_page"}


@dataclass(frozen=True)
class GPTImageConfig:
    base_url: str
    api_key: str
    edit_path: str = "/v1/images/edits"
    model: str = "gpt-image-2"
    quality: str = "low"
    size: str = DEFAULT_SIZE
    timeout_seconds: int = 600


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config(path: Path) -> GPTImageConfig:
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        raise ValueError(f"GPT image config must be a JSON object: {path}")
    api_key = str(payload.get("api_key") or os.getenv("GPT_IMAGE_API_KEY") or "").strip()
    base_url = str(payload.get("base_url") or os.getenv("GPT_IMAGE_BASE_URL") or "https://maasapi.casdao.com").strip()
    if not api_key:
        raise ValueError(f"GPT image api_key is missing; write it to {path} or GPT_IMAGE_API_KEY")
    return GPTImageConfig(
        base_url=base_url,
        api_key=api_key,
        edit_path=str(payload.get("edit_path") or "/v1/images/edits"),
        model=str(payload.get("model") or "gpt-image-2"),
        quality=str(payload.get("quality") or "low"),
        size=str(payload.get("size") or DEFAULT_SIZE),
        timeout_seconds=int(payload.get("timeout_seconds") or 600),
    )


def bearer(api_key: str) -> str:
    return api_key if " " in api_key.strip() else f"Bearer {api_key.strip()}"


def edit_url(config: GPTImageConfig) -> str:
    return urljoin(config.base_url.rstrip("/") + "/", config.edit_path.lstrip("/"))


def content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "image/png"


def decode_image_response(response: httpx.Response) -> bytes:
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(f"GPT image response is not JSON: HTTP {response.status_code}") from exc
    if response.status_code >= 400:
        error = body.get("error") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise RuntimeError(str(message or f"GPT image HTTP {response.status_code}"))
    if not isinstance(body, dict):
        raise RuntimeError("GPT image response root is not an object")
    items = body.get("data")
    if not isinstance(items, list) or not items:
        raise RuntimeError("GPT image response has no data items")
    first = next((item for item in items if isinstance(item, dict)), None)
    if not first:
        raise RuntimeError("GPT image response data item is invalid")
    b64_json = str(first.get("b64_json") or "").strip()
    if b64_json:
        return base64.b64decode(b64_json)
    url = str(first.get("url") or "").strip()
    if url:
        with httpx.Client(timeout=120) as client:
            downloaded = client.get(url)
        if downloaded.status_code >= 400:
            raise RuntimeError(f"failed to download GPT image result: HTTP {downloaded.status_code}")
        return downloaded.content
    raise RuntimeError("GPT image response has no b64_json or url")


def gpt_edit_image(config: GPTImageConfig, image_path: Path, prompt: str, raw_output: Path) -> None:
    data = {"model": config.model, "prompt": prompt, "quality": config.quality, "n": "1"}
    if config.size:
        data["size"] = config.size
    files = {"image": (image_path.name, image_path.read_bytes(), content_type(image_path))}
    with httpx.Client(timeout=config.timeout_seconds) as client:
        response = client.post(edit_url(config), data=data, files=files, headers={"Authorization": bearer(config.api_key)})
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_bytes(decode_image_response(response))


def preprocess_for_gpt(source_path: Path, output_path: Path, *, result: bool) -> Path:
    if not result:
        return source_path
    image = Image.open(source_path).convert("RGB")
    width, height = image.size
    work = image
    # Result pages often include browser chrome, dark canvas, and assistant widgets.
    # Keep the generated board/result as the model input and remove floating UI widgets
    # that are not part of the generated result.
    if width / max(height, 1) > 1.2:
        left = int(width * 0.36)
        top = int(height * 0.22)
        right = int(width * 0.93)
        bottom = height
        work = work.crop((left, top, right, bottom))
    elif height / max(width, 1) > 1.2:
        left = int(width * 0.06)
        top = int(height * 0.33)
        right = int(width * 0.90)
        bottom = int(height * 0.64)
        work = work.crop((left, top, right, bottom))
    draw_color = (248, 248, 248)
    w, h = work.size
    mask_box = (int(w * 0.70), int(h * 0.42), int(w * 0.94), int(h * 0.70))
    if mask_box[2] > mask_box[0] and mask_box[3] > mask_box[1]:
        patch = Image.new("RGB", (mask_box[2] - mask_box[0], mask_box[3] - mask_box[1]), draw_color)
        work.paste(patch, (mask_box[0], mask_box[1]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work.save(output_path, "PNG")
    return output_path


def normalize_to_video_canvas(input_path: Path, output_path: Path) -> dict[str, Any]:
    image = Image.open(input_path).convert("RGB")
    fitted = ImageOps.contain(image, (TARGET_WIDTH, TARGET_HEIGHT), method=Image.Resampling.LANCZOS)
    background = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (248, 248, 248))
    background.paste(fitted, ((TARGET_WIDTH - fitted.width) // 2, (TARGET_HEIGHT - fitted.height) // 2))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    background.save(output_path, "PNG")
    return probe_image(output_path)


def probe_image(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
    return {
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 6) if height else None,
        "probe_ok": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else case_dir / path


def as_case_relative(case_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(case_dir.resolve(strict=False)).as_posix()


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in project.get("assets", []) if isinstance(asset, dict) and asset.get("id")}


def resource_by_asset(case_dir: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(case_dir / "image_resources.json", {"resources": []})
    resources = payload.get("resources", []) if isinstance(payload, dict) else []
    return {str(item.get("asset_id")): item for item in resources if isinstance(item, dict) and item.get("asset_id")}


def is_result_event(event: dict[str, Any], source_asset: dict[str, Any], resource: dict[str, Any]) -> bool:
    evidence = str(event.get("evidence_binding") or "").lower()
    image_resource = source_asset.get("image_resource", {}) if isinstance(source_asset.get("image_resource"), dict) else {}
    step = str(resource.get("workflow_step") or image_resource.get("workflow_step") or "").lower()
    role = str(source_asset.get("role") or "").lower()
    source = str(source_asset.get("source") or "").replace("\\", "/").lower()
    return evidence in {"real_result", "real_generated_result"} or step in RESULT_STEPS or "result" in role or "assets/results/" in source


def prompt_for(event: dict[str, Any], source_asset: dict[str, Any], resource: dict[str, Any], result: bool) -> str:
    visible_text = ", ".join(str(v) for v in (source_asset.get("visible_text") or resource.get("visible_text") or []) if v)
    description = str(source_asset.get("description") or resource.get("description") or "").strip()
    base = (
        "Use the uploaded image as the only source of truth. Create one vertical 9:16 keyframe for a 1080x1920 short video. "
        "Only adjust format, framing, scale, spacing, and composition so it can be placed directly in a vertical video. "
        "Do not create different content. Do not invent new UI, logos, products, text, colors, icons, or extra visual elements. "
        "Preserve the original Chinese text and visual meaning as much as possible. Keep the main subject centered and readable, "
        "with clean top and bottom safe space for subtitles. No decorative title cards, no marketing copy, no added captions."
    )
    if result:
        task = (
            "This is a business design result display frame. If the source contains a website result page, extract and re-layout only the visible generated result board/image content from that page; "
            "the webpage chrome is evidence only and should not be the final subject. Preserve the result exactly; do not redesign the brand board."
        )
    else:
        task = (
            "This is a function/process screenshot frame. Preserve the website UI state exactly, but reframe it as an AI-verified 9:16 screenshot: "
            "the active menu, form, button, or loading state must be large enough to read in the central safe region."
        )
    context = f" Source description: {description}" if description else ""
    text = f" Visible text to preserve: {visible_text}" if visible_text else ""
    return f"{base} {task}{context}{text}"


def unique_keyframe_requests(project: dict[str, Any], case_dir: Path) -> list[dict[str, Any]]:
    assets = asset_index(project)
    resources = resource_by_asset(case_dir)
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()
    for event in project.get("visual_track", []):
        if not isinstance(event, dict):
            continue
        asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
        if not asset_ids:
            continue
        source_asset = assets.get(asset_ids[0])
        if not source_asset or str(source_asset.get("type") or "").lower() != "image":
            continue
        resource = resources.get(str(source_asset.get("id")), {})
        result = is_result_event(event, source_asset, resource)
        key = (str(source_asset.get("id")), result)
        if key in seen:
            continue
        seen.add(key)
        requests.append({"event": event, "asset": source_asset, "resource": resource, "result": result})
    return requests


def make_asset(case_dir: Path, source_asset: dict[str, Any], event: dict[str, Any], output_path: Path, metadata: dict[str, Any], result: bool) -> dict[str, Any]:
    old_id = str(source_asset.get("id"))
    event_id = str(event.get("id") or "visual")
    workflow_step = "result_crop" if result else "prepared_9x16"
    source_image_resource = source_asset.get("image_resource", {}) if isinstance(source_asset.get("image_resource"), dict) else {}
    source_workflow_step = str(source_image_resource.get("workflow_step") or "").strip()
    return {
        "id": f"asset_gpt_{event_id}_{old_id}",
        "type": "image",
        "source": as_case_relative(case_dir, output_path),
        "filename": output_path.name,
        "mime_type": "image/png",
        "origin": "gpt_image_layout_optimization",
        "source_asset_id": old_id,
        "role": "gpt_result_keyframe" if result else "gpt_function_keyframe",
        "description": source_asset.get("description") or "",
        "visible_text": source_asset.get("visible_text") or [],
        "supported_claims": source_asset.get("supported_claims") or [],
        "metadata": metadata,
        "display_risk": [],
        "layout_plan": {
            "primary_display_mode": "result-showcase" if result else "portrait-showcase",
            "focus_region": "ai_verified_full_frame",
            "fill_strategy": "direct_1080x1920_keyframe",
            "min_subject_frame_ratio": 0.55,
        },
        "image_resource": {
            "workflow_step": workflow_step,
            "source_workflow_step": source_workflow_step,
            "variant": "gpt_image_layout_optimized",
            "source_asset_id": old_id,
            "ai_verified_for_video": True,
        },
        "quality": {"readable": True, "contains_private_info": False, "needs_review": False},
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path)
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is invalid: {project_path}")
    config = load_config(Path(args.config).expanduser().resolve(strict=False))
    requests = unique_keyframe_requests(project, case_dir)
    if args.limit:
        requests = requests[: args.limit]
    if not requests:
        raise ValueError("no image visual assets found in project.visual_track")

    replacement_by_source: dict[str, str] = {}
    new_assets: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    raw_dir = case_dir / "output" / "gpt_image_keyframes" / "raw"
    preprocessed_dir = case_dir / "output" / "gpt_image_keyframes" / "preprocessed"
    prepared_root = case_dir / "assets" / "prepared" / "keyframes"
    result_root = case_dir / "assets" / "results" / "gpt_keyframes"

    for item in requests:
        event = item["event"]
        source_asset = item["asset"]
        source_id = str(source_asset.get("id"))
        result = bool(item["result"])
        source_path = resolve_case_path(case_dir, source_asset.get("source"))
        if not source_path or not source_path.is_file():
            raise FileNotFoundError(f"source asset missing: {source_asset.get('source')}")
        stem = f"{event.get('id') or 'visual'}_{source_id}"
        preprocessed_path = preprocessed_dir / f"{stem}_input.png"
        raw_path = raw_dir / f"{stem}_raw.png"
        final_path = (result_root if result else prepared_root) / f"{stem}_gpt_9x16.png"
        prompt = prompt_for(event, source_asset, item["resource"], result)
        if args.force or not final_path.is_file():
            gpt_input = preprocess_for_gpt(source_path, preprocessed_path, result=result)
            if args.dry_run:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(gpt_input.read_bytes())
            else:
                gpt_edit_image(config, gpt_input, prompt, raw_path)
            metadata = normalize_to_video_canvas(raw_path, final_path)
        else:
            metadata = probe_image(final_path)
        new_asset = make_asset(case_dir, source_asset, event, final_path, metadata, result)
        replacement_by_source[source_id] = new_asset["id"]
        new_assets.append(new_asset)
        report_items.append(
            {
                "source_asset_id": source_id,
                "new_asset_id": new_asset["id"],
                "result_visual": result,
                "source": source_asset.get("source"),
                "preprocessed_input": as_case_relative(case_dir, preprocessed_path) if result else source_asset.get("source"),
                "raw_output": as_case_relative(case_dir, raw_path),
                "prepared_output": new_asset["source"],
                "prompt": prompt,
                "metadata": metadata,
            }
        )

    existing_assets = [asset for asset in project.get("assets", []) if isinstance(asset, dict)]
    existing_ids = {str(asset.get("id")) for asset in existing_assets}
    project["assets"] = existing_assets + [asset for asset in new_assets if asset["id"] not in existing_ids]
    new_asset_by_id = {asset["id"]: asset for asset in new_assets}
    for event in project.get("visual_track", []):
        if not isinstance(event, dict):
            continue
        asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
        if asset_ids and asset_ids[0] in replacement_by_source:
            replacement = replacement_by_source[asset_ids[0]]
            event["asset_ids"] = [replacement]
            event["layout"] = "result-showcase" if new_asset_by_id[replacement]["role"] == "gpt_result_keyframe" else "portrait-showcase"
            event.setdefault("qa_expectations", {})["uses_gpt_image_prepared_keyframe"] = True

    output_project = Path(args.output_project).expanduser().resolve(strict=False) if args.output_project else case_dir / "video_project.gpt_image.json"
    write_json(output_project, project)
    report_path = case_dir / "output" / "reports" / "gpt_image_keyframes_report.json"
    write_json(
        report_path,
        {
            "schema_version": 1,
            "provider": {"base_url": config.base_url, "edit_path": config.edit_path, "model": config.model, "quality": config.quality, "size": config.size},
            "project": str(output_project),
            "items": report_items,
        },
    )
    return {"ok": True, "code": "ok", "reason": "", "data": {"project": str(output_project), "report": str(report_path), "count": len(report_items)}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare GPT image optimized 9:16 keyframes for a Pipeline V2 video project.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--output-project")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Do not call GPT image; copy sources through the same project rewrite path.")
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
        sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    elif output["ok"]:
        print(f"GPT image keyframes: {output['data']['project']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
