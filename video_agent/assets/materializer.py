from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from video_agent.ai.gpt_image import edit_image
from video_agent.ai.prompt_loader import load_prompt
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    DeriveKind,
    EvidenceClass,
    MaterializationPlan,
    Provenance,
)
from video_agent.io import sha256_file, sha256_json, utc_now


CANVAS_SIZE = (1080, 1920)
SITE_KINDS = {
    DeriveKind.SITE_HOME_KEYFRAME,
    DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME,
    DeriveKind.PARAMETER_CALLOUT_SEQUENCE,
}
FAITHFUL_KINDS = {
    DeriveKind.CROP_AND_REFRAME,
    DeriveKind.RESULT_DETAIL_CROP,
    DeriveKind.RESULT_VERTICAL_LAYOUT,
    DeriveKind.RESULT_COLLECTION,
    DeriveKind.VIDEO_SAFE_RELAYOUT,
}
GPT_KINDS = SITE_KINDS | {
    DeriveKind.CANVAS_EXTEND,
    DeriveKind.LOGO_ISOLATE_SEMANTIC,
    DeriveKind.BRAND_IP_SUBTITLE_BREAK,
    DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION,
    DeriveKind.TEXT_VISUAL_BREAK,
    DeriveKind.RESULT_TO_REFERENCE_MOCK,
    DeriveKind.LOGO_TO_REFERENCE_BOARD,
    DeriveKind.RESULT_TO_APPLICATION,
    DeriveKind.RESULT_TO_FLAT_PLAN,
    DeriveKind.RESULT_TO_EDIT_STATE,
    DeriveKind.RESULT_TO_VARIATION,
    DeriveKind.CONTEXTUAL_RESULT_FILL,
    DeriveKind.GALLERY_PREVIEW,
    DeriveKind.RESULT_TO_EDITOR_COMPOSITE,
}


def _prompt(repo_root: Path, kind: DeriveKind, instruction: str) -> tuple[str, str]:
    recipes = {
        DeriveKind.CANVAS_EXTEND: "Extend only the surrounding canvas; keep the source image itself unchanged and fully visible.",
        DeriveKind.SITE_HOME_KEYFRAME: "Create a close, readable 9:16 keyframe from the website's first viewport only. Let the 文生图 module occupy most of the safe screen and make it the visual focus using an elegant integrated highlight. Crop away the lower case-resource library and unrelated below-the-fold content. Preserve visible UI, Chinese text, colors, and layout relationships; do not invent or rewrite content.",
        DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME: "Create a close, readable 9:16 keyframe from the website's upper first viewport. The left 文生图 navigation item and its open hover menu are the required subject; do not treat the homepage shortcut pills as the navigation entry. Let the hover menu occupy most of the safe screen. Add exactly one conspicuous red hand-drawn double-stroke circle or ellipse around the named target item inside the hover menu. Adapt the shape naturally to the target text and keep generous breathing room. The mark may overlap empty menu spacing naturally, but it must not enclose or visually point to any adjacent label. Do not use a rigid table-cell rectangle. Crop away the lower case-resource library and unrelated below-the-fold content. Do not invent UI, rewrite Chinese text, add a fake cursor, or change the selected feature. The generated image is the final visual marker; do not create or imply a separate reveal layer.",
        DeriveKind.LOGO_ISOLATE_SEMANTIC: "Create a semantic presentation of the existing logo on a clean background; do not claim pixel-perfect extraction.",
        DeriveKind.BRAND_IP_SUBTITLE_BREAK: "Create a restrained brand interlude using only the visible brand or IP element from the source.",
        DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION: "Compose the visible identity element and the original complete design system as a clear before-to-system frame.",
        DeriveKind.TEXT_VISUAL_BREAK: "Create a restrained branded visual break. Do not add product facts, fake UI, or unsupported result claims.",
        DeriveKind.PARAMETER_CALLOUT_SEQUENCE: "Preserve the complete real parameter-page UI and every original Chinese label. Add a clear, video-ready flower-text callout for the required fields named in the instruction. Do not invent controls or remove required red asterisks.",
        DeriveKind.RESULT_TO_REFERENCE_MOCK: "Create a plausible empty-scene reference image that could precede the supplied design result. Preserve exactly the same landscape camera crop, wall boundaries, floor, ceiling, lighting, perspective, and major architectural objects; remove only the finished design treatment. Fill the whole output with the scene itself. This is a workflow illustration, not a real historical photograph.",
        DeriveKind.LOGO_TO_REFERENCE_BOARD: "Create a restrained visual reference board whose forms, materials, and mood plausibly lead to the supplied logo. Keep the supplied logo unchanged and do not invent another brand.",
        DeriveKind.RESULT_TO_APPLICATION: "Place the supplied design into one coherent real-world application while preserving the original design, typography, colors, and brand identity.",
        DeriveKind.RESULT_TO_FLAT_PLAN: "Transform the supplied installed design result into the corresponding clean front-facing flat artwork. Remove the photographed architecture and perspective while preserving the complete wall design, theme, major text, graphics, colors, and their spatial relationships. Use the same landscape aspect ratio as the source and fill the whole output with the flat artwork; do not add a gray presentation canvas.",
        DeriveKind.RESULT_TO_EDIT_STATE: "Create a clearly visible but coherent edited state of the supplied result. Preserve the exact landscape camera crop, dimensions, architecture, typography, and all untouched content. Apply only the requested local change. If the instruction is vague, visibly change one local accent color and one small decorative motif without redesigning the whole image, so a before/after comparison is immediately legible.",
        DeriveKind.RESULT_TO_VARIATION: "Create one closely related design variation while preserving the source subject, brand, function, and visual identity.",
        DeriveKind.CONTEXTUAL_RESULT_FILL: "Use the supplied approved result image only as a visual-quality and composition reference. Create the concrete missing design category named in the instruction, with a complete, credible final result suitable for a short-video gallery. The target category and scene must follow the instruction exactly. Do not copy source-specific brands, factual claims, readable slogans, or pretend that the generated image is source evidence. Keep the source orientation unless the instruction explicitly requires another orientation.",
        DeriveKind.GALLERY_PREVIEW: "Create a clean quick-gallery preview matching the requested group orientation. Preserve every important source element, all panels, products, text blocks, brand colors, and factual design. Recompose the existing elements only as needed to fill the target aspect ratio; never summarize, remove panels, squeeze the source, or add a gray/dark presentation canvas.",
        DeriveKind.RESULT_TO_EDITOR_COMPOSITE: "The first supplied panel is the design result and the second is the real editor UI. Place the complete first result naturally into the editor canvas shown in the second panel. Preserve the editor controls and the result content; do not redesign either source.",
    }
    if kind not in recipes:
        raise ValueError(f"derive kind has no GPT Image recipe: {kind.value}")
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "materialization" / "controlled_derivative.md")
    return prompt.text.format(recipe=recipes[kind], instruction=instruction or "none"), prompt.sha256


def _resolve_source(repo_root: Path, asset: Asset) -> Path:
    raw = Path(asset.path)
    path = raw if raw.is_absolute() else repo_root / raw
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"asset source is missing: {asset.asset_id}/{path}")
    return path


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", value).strip("_")
    return cleaned or "派生素材"


def _provider_signature(repo_root: Path) -> dict[str, str]:
    path = repo_root / "config" / "gpt_image.local.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        raw = {}
    providers = raw.get("providers") if isinstance(raw.get("providers"), list) else []
    first = providers[0] if providers and isinstance(providers[0], dict) else raw
    return {
        "provider": str(first.get("name") or "gpt_image"),
        "base_url": str(first.get("base_url") or raw.get("base_url") or "").rstrip("/"),
        "model": str(first.get("model") or raw.get("model") or "gpt-image-2"),
        "size": str(first.get("size") or raw.get("size") or "1024x1792"),
    }


def _target_size(orientation: str | None, signature: dict[str, str]) -> str:
    configured = str(signature.get("size") or "")
    if orientation == "landscape":
        if "x" in configured:
            width, height = configured.lower().split("x", 1)
            if width.isdigit() and height.isdigit():
                return f"{max(int(width), int(height))}x{min(int(width), int(height))}"
        return "1792x1024"
    if orientation == "square":
        return "1024x1024"
    if "x" in configured:
        width, height = configured.lower().split("x", 1)
        if width.isdigit() and height.isdigit():
            return f"{min(int(width), int(height))}x{max(int(width), int(height))}"
    return "1024x1792"


def _combined_input(paths: list[Path], output: Path) -> Path:
    if len(paths) == 1:
        return paths[0]
    panel_w, panel_h = 1024, 1024
    canvas = Image.new("RGB", (panel_w * len(paths), panel_h), (12, 15, 20))
    draw = ImageDraw.Draw(canvas)
    for index, path in enumerate(paths):
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((panel_w - 32, panel_h - 56), Image.Resampling.LANCZOS)
            x = index * panel_w + (panel_w - image.width) // 2
            y = 40 + (panel_h - 40 - image.height) // 2
            canvas.paste(image, (x, y))
        draw.text((index * panel_w + 16, 12), chr(ord("A") + index), fill=(255, 212, 74))
    canvas.save(output, format="PNG")
    return output


def _fit_size(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    scale = min(max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _blurred_canvas(image: Image.Image) -> Image.Image:
    background = image.convert("RGB")
    scale = max(CANVAS_SIZE[0] / background.width, CANVAS_SIZE[1] / background.height)
    background = background.resize(
        (max(1, round(background.width * scale)), max(1, round(background.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (background.width - CANVAS_SIZE[0]) // 2)
    top = max(0, (background.height - CANVAS_SIZE[1]) // 2)
    background = background.crop((left, top, left + CANVAS_SIZE[0], top + CANVAS_SIZE[1]))
    return background.filter(ImageFilter.GaussianBlur(42)).convert("RGB")


def _paste_fitted(canvas: Image.Image, image: Image.Image, *, max_width: int = 930, max_height: int = 1520) -> None:
    resized = image.convert("RGB").resize(_fit_size(image.width, image.height, max_width, max_height), Image.Resampling.LANCZOS)
    x = (canvas.width - resized.width) // 2
    y = 220 + (max_height - resized.height) // 2
    canvas.paste(resized, (x, y))


def _deterministic_reframe(source: Path, output: Path) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        canvas = Image.new("RGB", CANVAS_SIZE, (7, 10, 14))
        _paste_fitted(canvas, image)
        canvas.save(output, format="PNG")


def _vertical_layout(source: Path, output: Path) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        canvas = _blurred_canvas(image)
        veil = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 95))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), veil).convert("RGB")
        _paste_fitted(canvas, image, max_width=950, max_height=1580)
        canvas.save(output, format="PNG")


def _detail_crop(source: Path, output: Path, asset: Asset) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        if asset.visual_anchors:
            rect = asset.visual_anchors[0].rect
            center_x = (rect.x + rect.w / 2) * image.width
            center_y = (rect.y + rect.h / 2) * image.height
            crop_width = max(rect.w * image.width * 3.0, image.width * 0.42)
            crop_height = max(rect.h * image.height * 4.0, image.height * 0.42)
        else:
            center_x, center_y = image.width / 2, image.height / 2
            crop_width, crop_height = image.width * 0.68, image.height * 0.68
        target_ratio = 0.78
        if crop_width / crop_height > target_ratio:
            crop_height = crop_width / target_ratio
        else:
            crop_width = crop_height * target_ratio
        crop_width = min(image.width, crop_width)
        crop_height = min(image.height, crop_height)
        left = max(0, min(image.width - crop_width, center_x - crop_width / 2))
        top = max(0, min(image.height - crop_height, center_y - crop_height / 2))
        crop = image.crop((round(left), round(top), round(left + crop_width), round(top + crop_height)))
        canvas = _blurred_canvas(crop)
        veil = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 85))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), veil).convert("RGB")
        _paste_fitted(canvas, crop, max_width=960, max_height=1640)
        canvas.save(output, format="PNG")


def _collection(sources: list[Path], output: Path) -> None:
    if not sources:
        raise ValueError("result_collection requires at least one source")
    canvas = Image.new("RGB", CANVAS_SIZE, (7, 10, 14))
    columns = 1 if len(sources) == 1 else 2
    rows = (len(sources) + columns - 1) // columns
    gap, margin = 28, 72
    width = (CANVAS_SIZE[0] - margin * 2 - gap * (columns - 1)) // columns
    height = (CANVAS_SIZE[1] - margin * 2 - gap * (rows - 1)) // rows
    boxes = [
        (margin + (index % columns) * (width + gap), margin + (index // columns) * (height + gap), width, height)
        for index in range(len(sources))
    ]
    for source, (x, y, w, h) in zip(sources, boxes, strict=True):
        with Image.open(source) as opened:
            image = opened.convert("RGB")
            scale = max(w / image.width, h / image.height)
            resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
            left = max(0, (resized.width - w) // 2)
            top = max(0, (resized.height - h) // 2)
            canvas.paste(resized.crop((left, top, left + w, top + h)), (x, y))
    canvas.save(output, format="PNG")


def _faithful_output(kind: DeriveKind, source: Path, output: Path, parent: Asset, related_sources: list[Path]) -> None:
    if kind == DeriveKind.CROP_AND_REFRAME:
        _deterministic_reframe(source, output)
    elif kind == DeriveKind.RESULT_DETAIL_CROP:
        _detail_crop(source, output, parent)
    elif kind == DeriveKind.RESULT_VERTICAL_LAYOUT:
        _vertical_layout(source, output)
    elif kind == DeriveKind.RESULT_COLLECTION:
        _collection([source, *related_sources], output)
    elif kind == DeriveKind.VIDEO_SAFE_RELAYOUT:
        _vertical_layout(source, output)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"unsupported faithful derive kind: {kind.value}")


def _write_registry(path: Path, registered: list[Asset], derived: list[Asset]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {asset.metadata.get("derivative_key") or asset.asset_id: asset for asset in [*registered, *derived]}
    path.write_text(
        json.dumps(
            {"schema_version": 1, "assets": [asset.model_dump(mode="json", exclude_none=True) for asset in merged.values()]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def materialize_assets(
    repo_root: Path,
    catalog: AssetCatalog,
    plan: MaterializationPlan,
    output_dir: Path,
    registry_path: Path | None = None,
) -> AssetCatalog:
    by_id = {asset.asset_id: asset for asset in catalog.assets}
    output_dir.mkdir(parents=True, exist_ok=True)
    derived: list[Asset] = []
    registered: list[Asset] = []
    if registry_path and registry_path.is_file():
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            registered = [Asset.model_validate(item) for item in payload.get("assets", [])]
        except (json.JSONDecodeError, ValueError):
            registered = []
    cached_by_key = {str(asset.metadata.get("derivative_key")): asset for asset in registered if asset.metadata.get("derivative_key")}
    for request in plan.requests:
        parent = by_id.get(request.source_asset_id)
        if parent is None:
            raise ValueError(f"derived request source is missing: {request.source_asset_id}")
        related = [by_id.get(asset_id) for asset_id in request.related_asset_ids]
        missing_related = [asset_id for asset_id, asset in zip(request.related_asset_ids, related, strict=False) if asset is None]
        if missing_related:
            raise ValueError(f"derived request related sources are missing: {missing_related}")
        parents = [parent, *[asset for asset in related if asset is not None]]
        if any(asset.media_type != "image" for asset in parents):
            raise ValueError(f"derived request sources must be images: {request.request_id}")
        if request.derive_kind not in FAITHFUL_KINDS | GPT_KINDS:
            raise ValueError(f"unsupported derive kind: {request.derive_kind.value}")
        if parent.provenance.origin == "site_screenshot_library":
            if request.derive_kind not in SITE_KINDS:
                raise ValueError("website screenshots cannot be redrawn outside GPT Image site keyframe recipes")
        elif request.derive_kind in SITE_KINDS:
            raise ValueError("site keyframe requests require a website screenshot source")
        if request.derive_kind in FAITHFUL_KINDS and any(
            asset.evidence_class not in {EvidenceClass.SOURCE, EvidenceClass.FAITHFUL} for asset in parents
        ):
            raise ValueError("faithful derivatives can only descend from E0/E1 assets")

        source = _resolve_source(repo_root, parent)
        related_sources = [_resolve_source(repo_root, asset) for asset in parents[1:]]
        prompt = ""
        prompt_sha256 = None
        provider = model = response_id = None
        evidence = EvidenceClass.FAITHFUL

        if request.derive_kind in GPT_KINDS:
            prompt, prompt_sha256 = _prompt(repo_root, request.derive_kind, request.instruction)
        signature = _provider_signature(repo_root) if request.derive_kind in GPT_KINDS else {"provider": "local", "base_url": "", "model": "faithful"}
        target_size = _target_size(request.target_orientation, signature) if request.derive_kind in GPT_KINDS else None
        if prompt and request.target_orientation:
            prompt += f"\nRequired output orientation: {request.target_orientation}. Required output size: {target_size}."
        derivative_key = sha256_json(
            {
                "sources": [asset.sha256 for asset in parents],
                "derive_kind": request.derive_kind.value,
                "instruction": request.instruction,
                "target_orientation": request.target_orientation,
                "relationship_id": request.relationship_id,
                "prompt_template_sha256": prompt_sha256,
                "provider": signature,
                "target_size": target_size,
            }
        )
        cached = cached_by_key.get(derivative_key)
        if cached:
            cached_path = _resolve_source(repo_root, cached)
            if sha256_file(cached_path) == cached.sha256:
                print(f"[素材准备] 复用已生成素材：{request.derive_kind.value} / {cached.filename}")
                derived.append(cached.model_copy(update={"metadata": {**cached.metadata, "request_id": request.request_id, "scene_id": request.scene_id}}))
                continue
        feature = request.semantic_path[-1] if request.semantic_path else parent.semantic_path[-1] if parent.semantic_path else "派生素材"
        output = output_dir / f"{_safe_name(feature)}_{request.derive_kind.value}_{derivative_key[:12]}.png"

        recovered_output = output.is_file()
        if recovered_output:
            try:
                with Image.open(output) as recovered:
                    recovered.verify()
            except OSError:
                output.unlink(missing_ok=True)
                recovered_output = False
        if recovered_output:
            print(f"[素材准备] 接管未注册的已生成素材：{output.name}")
            if request.derive_kind in GPT_KINDS:
                provider = str(signature.get("provider") or "unknown")
                model = str(signature.get("model") or "unknown")
                evidence = EvidenceClass.SEMANTIC
        elif request.derive_kind in FAITHFUL_KINDS:
            _faithful_output(request.derive_kind, source, output, parent, related_sources)
        else:
            print(f"[GPT Image] 补充素材中：{feature} / {request.derive_kind.value}")
            combined = _combined_input([source, *related_sources], output_dir / f".{derivative_key}.input.png")
            result = edit_image(repo_root, combined, prompt, size=target_size)
            output.write_bytes(result.content)
            if combined != source:
                combined.unlink(missing_ok=True)
            provider, model, response_id = result.provider, result.model, result.response_id
            evidence = EvidenceClass.SEMANTIC
            print(f"[GPT Image] 补充素材完成：{output.relative_to(repo_root).as_posix()}")

        with Image.open(output) as image:
            width, height = image.size
            image.verify()
        digest = sha256_file(output)
        short = hashlib.sha256(f"{request.request_id}|{digest}".encode("utf-8")).hexdigest()[:12]
        inherited_claims = list(dict.fromkeys(claim for asset in parents for claim in asset.claims))
        if request.derive_kind in SITE_KINDS:
            provenance_origin = "gpt_image_site_keyframe"
        elif evidence == EvidenceClass.SEMANTIC:
            provenance_origin = "gpt_image_semantic_derivative"
        else:
            provenance_origin = "deterministic_faithful_derivative"
        output_role = request.output_role or parent.role
        if request.output_role == "derived_image":
            output_role = {
                DeriveKind.SITE_HOME_KEYFRAME: "site_home",
                DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME: "feature_entry",
            }.get(request.derive_kind, parent.role)
        derived.append(
            Asset(
                asset_id=f"asset_derived_{short}",
                path=output.resolve().as_posix(),
                sha256=digest,
                filename=output.name,
                width=width,
                height=height,
                semantic_path=request.semantic_path or parent.semantic_path,
                role=output_role,
                evidence_class=evidence,
                claims=[] if evidence == EvidenceClass.SEMANTIC else inherited_claims,
                tags=list(dict.fromkeys(parent.tags + request.tags + [request.derive_kind.value])),
                identity_group=parent.identity_group,
                quality=AssetQuality(
                    status="machine_checked",
                    readable=None,
                    checks=["image_decode_ok"] + (["prompt_provenance_recorded"] if evidence == EvidenceClass.SEMANTIC else ["faithful_recipe_checked"]),
                ),
                provenance=Provenance(
                    origin=provenance_origin,
                    parent_asset_ids=[asset.asset_id for asset in parents],
                    provider=provider,
                    model=model,
                    prompt_sha256=sha256_json(prompt) if prompt else None,
                    response_id=response_id,
                ),
                metadata={
                    "derive_kind": request.derive_kind.value,
                    "request_id": request.request_id,
                    "scene_id": request.scene_id,
                    "semantic_phrase": request.semantic_phrase,
                    "target_orientation": request.target_orientation,
                    "target_size": target_size,
                    "preserve": request.preserve,
                    "prompt_template_sha256": prompt_sha256,
                    "purpose": request.purpose,
                    "relationship_id": request.relationship_id,
                    "beat_id": request.beat_id,
                    "preferred_start_frame": request.preferred_start_frame,
                    "preferred_end_frame": request.preferred_end_frame,
                    "derivative_key": derivative_key,
                },
            )
        )
        if registry_path:
            _write_registry(registry_path, registered, derived)
    if registry_path:
        _write_registry(registry_path, registered, derived)
    existing_ids = {asset.asset_id for asset in catalog.assets}
    return AssetCatalog(
        catalog_id=f"materialized_{catalog.catalog_id}",
        generated_at=utc_now(),
        source_root=catalog.source_root,
        assets=catalog.assets + [asset for asset in derived if asset.asset_id not in existing_ids],
        source_catalog_sha256=catalog.source_catalog_sha256,
        warnings=list(catalog.warnings),
    )
