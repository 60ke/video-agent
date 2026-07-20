from __future__ import annotations

from pathlib import Path

from video_agent.contracts import AssetCatalog
from video_agent.io import write_json_atomic

from .catalog import build_catalog as _build_catalog
from .catalog import catalog_snapshot
from .editor_flow import generate_editor_flow_assets
from .materializer import materialize_assets


def build_catalog(assets_root: Path, output_path: Path | None = None) -> AssetCatalog:
    catalog = _build_catalog(assets_root, None)
    if output_path:
        write_json_atomic(output_path, catalog)
    return catalog


__all__ = ["build_catalog", "catalog_snapshot", "generate_editor_flow_assets", "materialize_assets"]
