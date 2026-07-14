from __future__ import annotations

from pathlib import Path

from video_agent.contracts import AssetCatalog
from video_agent.io import sha256_json, write_json_atomic

from .catalog import build_catalog as _build_catalog
from .catalog import catalog_snapshot
from .materializer import materialize_assets
from .review import review_materialized_assets


_DEPRECATED_SITE_LAYER_KEYS = {
    "callout_base_path",
    "callout_base_sha256",
    "callout_layer_path",
    "callout_layer_sha256",
    "callout_layer_method",
}


def build_catalog(assets_root: Path, output_path: Path | None = None) -> AssetCatalog:
    catalog = _build_catalog(assets_root, None)
    for asset in catalog.assets:
        if asset.provenance.origin != "gpt_image_site_keyframe":
            continue
        for key in _DEPRECATED_SITE_LAYER_KEYS:
            asset.metadata.pop(key, None)
    catalog.source_catalog_sha256 = sha256_json([asset.model_dump(mode="json") for asset in catalog.assets])
    if output_path:
        write_json_atomic(output_path, catalog)
    return catalog


__all__ = ["build_catalog", "catalog_snapshot", "materialize_assets", "review_materialized_assets"]
