from __future__ import annotations

from pathlib import Path

from video_agent.contracts import AssetCatalog, EvidenceClass
from video_agent.io import sha256_json, write_json_atomic

from .catalog import build_catalog as _build_catalog
from .catalog import catalog_snapshot
from .materializer import materialize_assets
from .review import review_materialized_assets


DETERMINISTIC_SITE_WORKFLOWS = {
    "site_feature_entry_deterministic_batch",
    "site_params_deterministic_batch",
}


def build_catalog(assets_root: Path, output_path: Path | None = None) -> AssetCatalog:
    catalog = _build_catalog(assets_root, None)
    for asset in catalog.assets:
        if asset.metadata.get("workflow") not in DETERMINISTIC_SITE_WORKFLOWS:
            continue
        asset.evidence_class = EvidenceClass.FAITHFUL
        asset.claims = list(dict.fromkeys([*asset.claims, "real_website_screenshot", asset.role]))
        asset.provenance.origin = "deterministic_site_keyframe"
        asset.metadata["derive_kind"] = "callout_overlay"
        if "deterministic_site_recipe_verified" not in asset.quality.checks:
            asset.quality.checks.append("deterministic_site_recipe_verified")
    catalog.source_catalog_sha256 = sha256_json([asset.model_dump(mode="json") for asset in catalog.assets])
    if output_path:
        write_json_atomic(output_path, catalog)
    return catalog


__all__ = ["build_catalog", "catalog_snapshot", "materialize_assets", "review_materialized_assets"]
