from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from video_agent.contracts import Asset, AssetCatalog, DeriveKind, EvidenceClass
from video_agent.io import sha256_file, utc_now


FAITHFUL_DERIVE_KINDS = {
    DeriveKind.CROP_AND_REFRAME.value,
    DeriveKind.RESULT_DETAIL_CROP.value,
    DeriveKind.RESULT_VERTICAL_LAYOUT.value,
    DeriveKind.RESULT_COLLECTION.value,
}
MATERIALIZED_ORIGINS = {
    "deterministic_faithful_derivative",
    "gpt_image_semantic_derivative",
    "gpt_image_site_keyframe",
}


def _asset_path(repo_root: Path, asset: Asset) -> Path:
    raw = Path(asset.path)
    return (raw if raw.is_absolute() else repo_root / raw).resolve()


def _append_check(asset: Asset, check: str) -> None:
    if check not in asset.quality.checks:
        asset.quality.checks.append(check)


def _parent_claims(asset: Asset, by_id: dict[str, Asset]) -> list[str]:
    return list(
        dict.fromkeys(
            claim
            for parent_id in asset.provenance.parent_asset_ids
            if parent_id in by_id
            for claim in by_id[parent_id].claims
        )
    )


def review_materialized_assets(repo_root: Path, catalog: AssetCatalog) -> tuple[AssetCatalog, dict[str, Any]]:
    by_id = {asset.asset_id: asset for asset in catalog.assets}
    checks: list[dict[str, Any]] = []
    counts = {"passed": 0, "needs_review": 0, "rejected": 0, "unchanged": 0}

    for asset in catalog.assets:
        if asset.provenance.origin not in MATERIALIZED_ORIGINS:
            counts["unchanged"] += 1
            continue

        path = _asset_path(repo_root, asset)
        failures: list[str] = []
        if not path.is_file():
            failures.append("output_missing")
        elif sha256_file(path) != asset.sha256:
            failures.append("sha256_mismatch")
        else:
            try:
                with Image.open(path) as image:
                    width, height = image.size
                    image.verify()
                if (asset.width, asset.height) != (width, height):
                    failures.append("dimension_mismatch")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"image_decode_failed:{exc.__class__.__name__}")

        missing_parents = [parent_id for parent_id in asset.provenance.parent_asset_ids if parent_id not in by_id]
        if missing_parents:
            failures.append("missing_parent_assets")

        if asset.evidence_class == EvidenceClass.FAITHFUL:
            derive_kind = str(asset.metadata.get("derive_kind") or "")
            if derive_kind not in FAITHFUL_DERIVE_KINDS:
                failures.append("derive_kind_not_faithful")
            invalid_parents = [
                parent_id
                for parent_id in asset.provenance.parent_asset_ids
                if parent_id in by_id and by_id[parent_id].evidence_class not in {EvidenceClass.SOURCE, EvidenceClass.FAITHFUL}
            ]
            if invalid_parents:
                failures.append("non_factual_parent")

        if failures:
            asset.quality.status = "rejected"
            asset.quality.rejection_reason = ", ".join(failures)
            for failure in failures:
                _append_check(asset, failure)
            counts["rejected"] += 1
            status = "rejected"
        elif asset.evidence_class == EvidenceClass.FAITHFUL:
            asset.claims = _parent_claims(asset, by_id)
            asset.quality.status = "machine_checked"
            asset.quality.readable = True
            asset.quality.rejection_reason = None
            for check in ("image_decode_ok", "sha256_verified", "provenance_verified", "faithful_recipe_checked"):
                _append_check(asset, check)
            counts["passed"] += 1
            status = "passed"
        elif asset.quality.status in {"human_approved", "vision_verified"}:
            asset.quality.readable = True
            asset.quality.rejection_reason = None
            for check in ("image_decode_ok", "sha256_verified", "prior_approval_preserved"):
                _append_check(asset, check)
            counts["passed"] += 1
            status = "passed"
        else:
            asset.quality.status = "unreviewed"
            _append_check(asset, "requires_visual_review")
            counts["needs_review"] += 1
            status = "needs_review"

        checks.append(
            {
                "asset_id": asset.asset_id,
                "status": status,
                "evidence_class": asset.evidence_class.value,
                "failures": failures,
            }
        )

    reviewed = AssetCatalog(
        catalog_id=f"reviewed_{catalog.catalog_id}",
        generated_at=utc_now(),
        source_root=catalog.source_root,
        assets=catalog.assets,
        source_catalog_sha256=catalog.source_catalog_sha256,
        warnings=list(catalog.warnings),
    )
    report = {
        "schema_version": 1,
        "generated_at": reviewed.generated_at,
        "catalog_id": reviewed.catalog_id,
        "counts": counts,
        "checks": checks,
    }
    return reviewed, report
