from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

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


GPT_KINDS = {
    DeriveKind.CANVAS_EXTEND,
    DeriveKind.SITE_HOME_KEYFRAME,
    DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME,
    DeriveKind.SITE_PARAMS_KEYFRAME,
    DeriveKind.LOGO_ISOLATE_SEMANTIC,
    DeriveKind.BRAND_IP_SUBTITLE_BREAK,
    DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION,
}


def _prompt(repo_root: Path, kind: DeriveKind, instruction: str) -> tuple[str, str]:
    recipes = {
        DeriveKind.CANVAS_EXTEND: "Extend only the surrounding canvas; keep the source image itself unchanged and fully visible.",
        DeriveKind.SITE_HOME_KEYFRAME: "Create a close, readable 9:16 keyframe from the website's first viewport only. Let the 文生图 module occupy most of the safe screen and make it the visual focus using an elegant integrated highlight. Crop away the lower case-resource library and unrelated below-the-fold content. Preserve visible UI, Chinese text, colors, and layout relationships; do not invent or rewrite content.",
        DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME: "Create a close, readable 9:16 keyframe from the website's upper first viewport. The left 文生图 navigation item and its open hover menu are the required subject; do not treat the homepage shortcut pills as the navigation entry. Let the hover menu occupy most of the safe screen. Add exactly one conspicuous red hand-drawn double-stroke circle or ellipse around the named target item inside the hover menu. Adapt the shape naturally to the target text: use a compact circle or small ellipse for short labels such as VI, and a wider ellipse for longer Chinese labels. Keep generous breathing room and place the target text near the visual center. The mark may overlap empty menu spacing naturally, but it must not enclose or visually point to any adjacent label. Do not use a rigid table-cell rectangle. Crop away the lower case-resource library and unrelated below-the-fold content. Do not invent UI, rewrite Chinese text, or change the selected feature.",
        DeriveKind.SITE_PARAMS_KEYFRAME: "Create a readable, interactive 9:16 parameter-panel keyframe. Preserve the original complete required-input area and the 开始生成 button, enlarge the panel for legibility, and preserve every visible UI field and Chinese label without rewriting content. The panel is the composition: crop and scale it to span the full usable frame width from left to right, with at most a 3% outer margin on either side. The output must never contain a blank right-side strip, right-side black space, side column, letterbox, split-screen, or any empty area that makes the parameter panel look narrow. Preserve every original red required asterisk/star symbol already visible in the UI exactly where it is: never remove, hide, recolor, restyle, move, duplicate, or replace an existing UI asterisk. The no-asterisk rule applies only to the newly added callout text. Render the injected callout text exactly, with no * character, and draw one hand-drawn curved arrow toward the supplied field area. Treat the callout and arrow as a bold overlay directly on top of the original parameter panel, preferentially in its right-side or lower-right area; do not reserve an empty region for it. The callout may overlap ordinary form content or the page background as needed for a strong, integrated composition. The sole placement prohibition is covering an original page title or section title. The injected callout text is the only new Chinese text allowed in the image. Never render source, validation, provenance, or instruction language such as 已验证必填字段, 必填字段, 字段说明, CDP, or 前端源码. Use a varied high-contrast style suited to the composition, such as marker handwriting with a contrasting arrow, outlined lettering with a brush underline, or a small sticker-style title with a scribbled pointer; do not always use the same color combination. Do not add people, avatars, fake cursor clicks, extra UI, red boxes, or invented field names.",
        DeriveKind.LOGO_ISOLATE_SEMANTIC: "Create a semantic presentation of the existing logo on a clean background; do not claim pixel-perfect extraction.",
        DeriveKind.BRAND_IP_SUBTITLE_BREAK: "Create a restrained brand interlude using only the visible brand or IP element from the source.",
        DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION: "Compose the visible identity element and the original complete design system as a clear before-to-system frame.",
    }
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "materialization" / "controlled_derivative.md")
    return prompt.text.format(recipe=recipes[kind], instruction=instruction or "none"), prompt.sha256


def _deterministic_reframe(source: Path, output: Path) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
        canvas = Image.new("RGB", (1080, 1920), (7, 10, 14))
        scale = min(900 / image.width, 1420 / image.height)
        resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        canvas.paste(resized, ((1080 - resized.width) // 2, 250 + (1420 - resized.height) // 2))
        canvas.save(output, format="PNG")


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
        if parent.media_type != "image":
            raise ValueError(f"derived request source is not an image: {request.source_asset_id}")
        site_kinds = {DeriveKind.SITE_HOME_KEYFRAME, DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME, DeriveKind.SITE_PARAMS_KEYFRAME}
        if parent.provenance.origin == "site_screenshot_library" and request.derive_kind in GPT_KINDS - site_kinds:
            raise ValueError("website screenshots cannot be redrawn by GPT Image")
        source = (repo_root / parent.path).resolve()
        output = output_dir / f"{request.request_id}.png"
        prompt = ""
        prompt_sha256 = None
        provider = model = response_id = None
        evidence = EvidenceClass.FAITHFUL
        if request.derive_kind == DeriveKind.CROP_AND_REFRAME:
            _deterministic_reframe(source, output)
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
        derived.append(
            Asset(
                asset_id=f"asset_derived_{short}",
                path=output.resolve().as_posix(),
                sha256=digest,
                filename=output.name,
                width=width,
                height=height,
                semantic_path=request.semantic_path or parent.semantic_path,
                role=request.output_role,
                evidence_class=evidence,
                claims=[] if evidence == EvidenceClass.SEMANTIC else list(parent.claims),
                tags=list(dict.fromkeys(parent.tags + request.tags + [request.derive_kind.value])),
                identity_group=parent.identity_group,
                quality=AssetQuality(
                    status="unreviewed" if evidence == EvidenceClass.SEMANTIC else "machine_checked",
                    readable=None,
                    checks=["image_decode_ok"] + (["requires_visual_review"] if evidence == EvidenceClass.SEMANTIC else []),
                ),
                provenance=Provenance(
                    origin="gpt_image_site_keyframe" if request.derive_kind in site_kinds else "gpt_image_semantic_derivative" if evidence == EvidenceClass.SEMANTIC else "deterministic_faithful_derivative",
                    parent_asset_ids=[parent.asset_id],
                    provider=provider,
                    model=model,
                    prompt_sha256=sha256_json(prompt) if prompt else None,
                    response_id=response_id,
                ),
                metadata={
                    "derive_kind": request.derive_kind.value,
                    "request_id": request.request_id,
                    "prompt_template_sha256": prompt_sha256,
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
