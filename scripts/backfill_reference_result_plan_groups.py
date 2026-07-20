"""Backfill at least one reference_result_plan causal group for Unit6.5/Unit7."""

from __future__ import annotations

from pathlib import Path

from video_agent.assets.v4 import AssetGroupDraft, AssetQuery, LocalObjectStore, SQLiteAssetRepository
from video_agent.contracts.v4 import AssetGroupMember
from video_agent.io import utc_now, write_json_atomic
from video_agent.progress import configure_logging, get_logger
from video_agent.registries import CapabilityRegistryHub


logger = get_logger()

# Prefer real-scene reference + any culture-wall result + flat_plan backfill member.
PREFERRED = {
    "category_id": "文生图/文化墙",
    "reference_object_key": "references/柯幻熊猫_文生图_文化墙_实景图_参考图_01.png",
    "flat_plan_object_key": "results/文生图/文化墙/平面图_01.jpg",
}


def main() -> int:
    configure_logging()
    root = Path(__file__).resolve().parents[1]
    hub = CapabilityRegistryHub.load(root / "config" / "registries" / "v4")
    repo = SQLiteAssetRepository(root / "var" / "v4" / "assets.sqlite3", LocalObjectStore(root / "assets"), hub)
    try:
        existing = repo.connection.execute(
            "select count(*) as c from asset_groups where pattern_id=? and status='active'",
            ("reference_result_plan",),
        ).fetchone()["c"]
        if existing:
            report = {"generated_at": utc_now(), "status": "exists", "count": existing}
            write_json_atomic(root / "var" / "v4" / "reference_result_plan_backfill_report.json", report)
            print(report)
            return 0

        category_id = PREFERRED["category_id"]
        references = repo.query_assets(
            AssetQuery(asset_roles=("reference_image",), active_only=True, category_ids=(category_id,))
        )
        results = repo.query_assets(
            AssetQuery(asset_roles=("result_image",), active_only=True, category_ids=(category_id,))
        )
        flats = repo.query_assets(
            AssetQuery(asset_roles=("flat_plan",), active_only=True, category_ids=(category_id,))
        )
        if not references or not results or not flats:
            raise RuntimeError(
                f"missing members for {category_id}: "
                f"reference={len(references)} result={len(results)} flat_plan={len(flats)}"
            )

        reference = next((asset for asset in references if asset.object_key == PREFERRED["reference_object_key"]), references[0])
        flat = next((asset for asset in flats if asset.object_key == PREFERRED["flat_plan_object_key"]), flats[0])
        result = results[0]
        members = [
            AssetGroupMember(member_key="reference_image", asset_role="reference_image", asset_ref=reference.asset_ref, order=1),
            AssetGroupMember(member_key="result_image", asset_role="result_image", asset_ref=result.asset_ref, order=2),
            AssetGroupMember(member_key="flat_plan", asset_role="flat_plan", asset_ref=flat.asset_ref, order=3),
        ]
        group = repo.register_group(
            AssetGroupDraft(
                group_type="causal",
                pattern_id="reference_result_plan",
                category_id=category_id,
                members=members,
            )
        )
        report = {
            "generated_at": utc_now(),
            "status": "registered",
            "group_ref": group.group_ref,
            "category_id": category_id,
            "members": [
                {"member_key": member.member_key, "asset_ref": member.asset_ref} for member in members
            ],
        }
        write_json_atomic(root / "var" / "v4" / "reference_result_plan_backfill_report.json", report)
        logger.info("[V4][unit6.5] registered reference_result_plan %s", group.group_ref)
        print(report)
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
