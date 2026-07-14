from __future__ import annotations

import hashlib
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
    DeriveKind.SITE_PARAMS_KEYFRAME,
}
FAITHFUL_KINDS = {
    DeriveKind.CROP_AND_REFRAME,
    DeriveKind.RESULT_DETAIL_CROP,
    DeriveKind.RESULT_VERTICAL_LAYOUT,
    DeriveKind.RESULT_COLLECTION,
    DeriveKind.CALLOUT_OVERLAY,
}
GPT_KINDS = SITE_KINDS | {
    DeriveKind.CANVAS_EXTEND,
    DeriveKind.LOGO_ISOLATE_SEMANTIC,
    DeriveKind.BRAND_IP_SUBTITLE_BREAK,
    DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION,
    DeriveKind.TEXT_VISUAL_BREAK,
}


def _prompt(repo_root: Path, kind: DeriveKind, instruction: str) -> tuple[str, str]:
    recipes = {
        DeriveKind.CANVAS_EXTEND: "Extend only the surrounding canvas; keep the source image itself unchanged and fully visible.",
        DeriveKind.SITE_HOME_KEYFRAME: "Create a close, readable 9:16 keyframe from the website's first viewport only. Let the 文生图 module occupy most of the safe screen and make it the visual focus using an elegant integrated highlight. Crop away the lower case-resource library and unrelated below-the-fold content. Preserve visible UI, Chinese text, colors, and layout relationships; do not invent or rewrite content.",
        DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME: "Create a close, readable 9:16 keyframe from the website's upper first viewport. The left 文生图 navigation item and its open hover menu are the required subject; do not treat the homepage shortcut pills as the navigation entry. Let the hover menu occupy most of the safe screen. Add exactly one conspicuous red hand-drawn double-stroke circle or ellipse around the named target item inside the hover menu. Adapt the shape naturally to the target text and keep generous breathing room. The mark may overlap empty menu spacing naturally, but it must not enclose or visually point to any adjacent label. Do not use a rigid table-cell rectangle. Crop away the lower case-resource library and unrelated below-the-fold content. Do not invent UI, rewrite Chinese text, add a fake cursor, or change the selected feature. The generated image is the final visual marker; do not create or imply a separate reveal layer.",
        DeriveKind.SITE_PARAMS_KEYFRAME: "Create a readable, interactive 9:16 parameter-panel keyframe. Preserve the original complete required-input area and the 开始生成 button, enlarge the panel for legibility, and preserve every visible UI field and Chinese label without rewriting content. The panel is the composition: crop and scale it to span the full usable frame width from left to right, with at most a 3% outer margin on either side. The output must never contain a blank right-side strip, right-side black space, side column, letterbox, split-screen, or any empty area that makes the parameter panel look narrow. Preserve every original red required asterisk/star symbol already visible in the UI exactly where it is. Render the injected callout text exactly, with no * character, and draw one hand-drawn curved arrow toward the supplied field area. Treat the callout and arrow as a bold integrated overlay directly on top of the original parameter panel; do not reserve an empty region for it. The injected callout text is the only new Chinese text allowed in the image. Never render source, validation, provenance, or instruction language such as 已验证必填字段, 必填字段, 字段说明, CDP, or 前端源码. Do not add people, avatars, fake cursor clicks, extra UI, red boxes, or invented field names. The generated image is the final visual marker; do not create a separate animation layer.",
        DeriveKind.LOGO_ISOLATE_SEMANTIC: "Create a semantic presentation of the existing logo on a clean background; do not claim pixel-perfect extraction.",
        DeriveKind.BRAND_IP_SUBTITLE_BREAK: "Create a restrained brand interlude using only the visible brand or IP element from the source.",
        DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION: "Compose the visible identity element and the original complete design system as a clear before-to-system frame.",
        DeriveKind.TEXT_VISUAL_BREAK: "Create a restrained branded visual break. Do not add product facts, fake UI, or unsupported result claims.",
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
    boxes = [(90, 190, 900, 720), (90, 990, 430, 650), (560, 990, 430, 650)]
    for source, (x, y, w, h) in zip(sources[:3], boxes, strict=False):
        with Image.open(source) as opened:
            image = opened.convert("RGB")
            scale = max(w / image.width, h / image.height)
            resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
            left = max(0, (resized.width - w) // 2)
            top = max(0, (resized.height - h) // 2)
            canvas.paste(resized.crop((left, top, left + w, top + h)), (x, y))
    canvas.save(output, format="PNG")


def _callout_overlay(source: Path, output: Path, asset: Asset) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        anchors = asset.visual_anchors[:1]
        if not anchors:
            raise ValueError(f"callout_overlay requires a visual anchor: {asset.asset_id}")
        rect = anchors[0].rect
        x0 = round((rect.x - rect.w * 0.25) * image.width)
        y0 = round((rect.y - rect.h * 0.45) * image.height)
        x1 = round((rect.x + rect.w * 1.25) * image.width)
        y1 = round((rect.y + rect.h * 1.45) * image.height)
        for offset, width in ((0, 8), (7, 4)):
            draw.ellipse((x0 - offset, y0 + offset, x1 + offset, y1 - offset), outline=(235, 45, 45, 255), width=width)
        composed = Image.alpha_composite(image, layer).convert("RGB")
        temporary = output.with_suffix(".source.png")
        composed.save(temporary, format="PNG")
        try:
            _vertical_layout(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)


def _faithful_output(kind: DeriveKind, source: Path, output: Path, parent: Asset, related_sources: list[Path]) -> None:
    if kind == DeriveKind.CROP_AND_REFRAME:
        _deterministic_reframe(source, output)
    elif kind == DeriveKind.RESULT_DETAIL_CROP:
        _detail_crop(source, output, parent)
    elif kind == DeriveKind.RESULT_VERTICAL_LAYOUT:
        _vertical_layout(source, output)
    elif kind == DeriveKind.RESULT_COLLECTION:
        _collection([source, *related_sources], output)
    elif kind == DeriveKind.CALLOUT_OVERLAY:
        _callout_overlay(source, output, parent)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"unsupported faithful derive kind: {kind.value}")


def materialize_assets(
    repo_root: Path,
    catalog: AssetCatalog,
    plan: MaterializationPlan,
    output_dir: Path,
) -> AssetCatalog:
    by_id = {asset.asset_id: asset for asset in catalog.assets}
    output_dir.mkdir(parents=True, exist_ok=True)
    derived: list[Asset] = []
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
        output = output_dir / f"{request.request_id}.png"
        prompt = ""
        prompt_sha256 = None
        provider = model = response_id = None
        evidence = EvidenceClass.FAITHFUL

        if request.derive_kind in FAITHFUL_KINDS:
            _faithful_output(request.derive_kind, source, output, parent, related_sources)
        else:
            prompt, prompt_sha256 = _prompt(repo_root, request.derive_kind, request.instruction)
            result = edit_image(repo_root, source, prompt)
            output.write_bytes(result.content)
            provider, model, response_id = result.provider, result.model, result.response_id
            evidence = EvidenceClass.SEMANTIC

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
                DeriveKind.SITE_PARAMS_KEYFRAME: "feature_form_params",
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
                    status="unreviewed" if evidence == EvidenceClass.SEMANTIC else "machine_checked",
                    readable=None,
                    checks=["image_decode_ok"] + (["requires_visual_review"] if evidence == EvidenceClass.SEMANTIC else ["faithful_recipe_checked"]),
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
                    "prompt_template_sha256": prompt_sha256,
                    "purpose": request.purpose,
                    "beat_id": request.beat_id,
                    "preferred_start_frame": request.preferred_start_frame,
                    "preferred_end_frame": request.preferred_end_frame,
                },
            )
        )
    return AssetCatalog(
        catalog_id=f"materialized_{catalog.catalog_id}",
        generated_at=utc_now(),
        source_root=catalog.source_root,
        assets=catalog.assets + derived,
        source_catalog_sha256=catalog.source_catalog_sha256,
        warnings=list(catalog.warnings),
    )
