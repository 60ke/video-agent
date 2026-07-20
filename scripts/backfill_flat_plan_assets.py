"""Register missing flat_plan role assets from known plane images for Unit6.5."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from video_agent.assets.v4 import AssetDraft, LocalObjectStore, SQLiteAssetRepository
from video_agent.contracts.v4 import EvidenceClass, Orientation, SourceKind
from video_agent.io import sha256_file, utc_now, write_json_atomic
from video_agent.progress import configure_logging, get_logger
from video_agent.registries import CapabilityRegistryHub


logger = get_logger()

# Existing plane-named files remapped to flat_plan production role.
PLANE_SOURCES = (
    ("assets/references/柯幻熊猫_文生图_文化墙_平面图_参考图_01.jpg", "文生图/文化墙", "results/文生图/文化墙/平面图_01.jpg"),
    ("assets/results/柯幻熊猫_文生图_门头招牌_平面_结果图_01.png", "文生图/门头招牌", "results/文生图/门头招牌/平面图_01.png"),
    ("assets/results/柯幻熊猫_文生图_景观小品_景观平面_结果图_01.png", "文生图/景观小品", "results/文生图/景观小品/平面图_01.png"),
)


def main() -> int:
    configure_logging()
    root = Path(__file__).resolve().parents[1]
    hub = CapabilityRegistryHub.load(root / "config" / "registries" / "v4")
    store = LocalObjectStore(root / "assets")
    db = root / "var" / "v4" / "assets.sqlite3"
    repo = SQLiteAssetRepository(db, store, hub)
    registered: list[dict[str, str]] = []
    try:
        existing = {
            asset.object_key: asset.asset_ref
            for asset in repo.query_assets(__import__("video_agent.assets.v4", fromlist=["AssetQuery"]).AssetQuery(asset_roles=("flat_plan",), active_only=False))
        }
        for source_rel, category_id, object_key in PLANE_SOURCES:
            if object_key in existing:
                registered.append({"object_key": object_key, "asset_ref": existing[object_key], "status": "exists"})
                continue
            source = root / source_rel
            if not source.is_file():
                raise FileNotFoundError(source)
            dest = root / "assets" / object_key
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                shutil.copy2(source, dest)
            with Image.open(dest) as image:
                width, height = image.size
            orientation = (
                Orientation.PORTRAIT
                if height > width
                else Orientation.LANDSCAPE
                if width > height
                else Orientation.SQUARE
            )
            module, *path_parts = category_id.split("/")
            if not path_parts:
                raise ValueError(f"category_id must include module and path: {category_id}")
            draft = AssetDraft(
                filename=dest.name,
                object_key=object_key.replace("\\", "/"),
                content_sha256=sha256_file(dest),
                media_type="image/jpeg" if dest.suffix.lower() in {".jpg", ".jpeg"} else "image/png",
                module=module,
                category_id=category_id,
                category_path=path_parts,
                asset_role="flat_plan",
                width=width,
                height=height,
                orientation=orientation,
                animated=False,
                source_kind=SourceKind.ORIGINAL,
                origin_type="unit65_flat_plan_backfill",
                evidence_class=EvidenceClass.SOURCE,
                claims=[],
            )
            record = repo.register_asset(draft)
            registered.append({"object_key": object_key, "asset_ref": record.asset_ref, "status": "registered"})
            logger.info("[V4][unit6.5] registered flat_plan %s -> %s", object_key, record.asset_ref)
        report = {"generated_at": utc_now(), "registered": registered}
        write_json_atomic(root / "var" / "v4" / "flat_plan_backfill_report.json", report)
        print(report)
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
