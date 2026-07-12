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
    DeriveKind.LOGO_ISOLATE_SEMANTIC,
    DeriveKind.BRAND_IP_SUBTITLE_BREAK,
    DeriveKind.IDENTITY_TO_SYSTEM_TRANSITION,
}


def _prompt(repo_root: Path, kind: DeriveKind, instruction: str) -> tuple[str, str]:
    recipes = {
        DeriveKind.CANVAS_EXTEND: "Extend only the surrounding canvas; keep the source image itself unchanged and fully visible.",
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
        if parent.provenance.origin == "site_screenshot_library" and request.derive_kind in GPT_KINDS:
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
                    origin="gpt_image_semantic_derivative" if evidence == EvidenceClass.SEMANTIC else "deterministic_faithful_derivative",
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
