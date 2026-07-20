"""Unit 6.5 production repository coverage gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from video_agent.assets.v4 import (
    AssetQuery,
    LocalObjectStore,
    SQLiteAssetRepository,
    audit_repository,
)
from video_agent.io import sha256_json, utc_now, write_json_atomic
from video_agent.progress import configure_logging, get_logger
from video_agent.registries import CapabilityRegistryHub


logger = get_logger()

REQUIRED_ROLES = (
    "site_home",
    "feature_entry",
    "parameter_panel",
    "result_image",
    "reference_image",
    "editor_page",
    "flat_plan",
    "outro",
)


def run_coverage_gate(*, db: Path, object_root: Path, output: Path, repo_root: Path) -> dict[str, Any]:
    hub = CapabilityRegistryHub.load(repo_root / "config" / "registries" / "v4")
    store = LocalObjectStore(object_root)
    repository = SQLiteAssetRepository(db, store, hub)
    try:
        audit = audit_repository(repository)
        checks: list[dict[str, Any]] = [
            {
                "check_id": "repository_audit",
                "status": "pass" if not audit.get("errors") else "fail",
                "errors": audit.get("errors") or [],
            }
        ]
        missing: list[str] = []
        if audit.get("errors"):
            missing.append("repository_audit")

        for role in REQUIRED_ROLES:
            assets = repository.query_assets(AssetQuery(asset_roles=(role,), active_only=True))
            status = "pass" if assets else "fail"
            checks.append({"role": role, "status": status, "count": len(assets)})
            if status == "fail":
                missing.append(role)

        causal_groups = repository.connection.execute(
            "select count(*) as c from asset_groups where pattern_id=? and status='active'",
            ("reference_result_plan",),
        ).fetchone()["c"]
        checks.append(
            {
                "check_id": "reference_result_plan_groups",
                "status": "pass" if causal_groups else "fail",
                "count": causal_groups,
            }
        )
        if not causal_groups:
            missing.append("reference_result_plan_groups")

        logo = repo_root / "assets/brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png"
        logo_ok = logo.is_file()
        checks.append({"role": "brand_logo", "status": "pass" if logo_ok else "fail", "path": logo.as_posix()})
        if not logo_ok:
            missing.append("brand_logo")

        report = {
            "schema_version": "v4.production_asset_coverage.1",
            "generated_at": utc_now(),
            "db": db.as_posix(),
            "object_root": object_root.as_posix(),
            "allow_fake_derivation": False,
            "passed": not missing,
            "missing": missing,
            "checks": checks,
            "fingerprint": sha256_json({"checks": checks, "missing": missing}),
        }
        write_json_atomic(output, report)
        return report
    finally:
        repository.close()


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Stage7 Unit6.5 production asset coverage gate")
    parser.add_argument("--db", default="var/v4/assets.sqlite3")
    parser.add_argument(
        "--object-root",
        default=None,
        help="Object store root. Defaults to config/assets.v4.json object_root (assets).",
    )
    parser.add_argument("--output", default="var/v4/production_asset_coverage_report.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    if args.object_root:
        object_root = Path(args.object_root).resolve()
    else:
        config_path = repo_root / "config" / "assets.v4.json"
        if config_path.is_file():
            object_root = (repo_root / json.loads(config_path.read_text(encoding="utf-8"))["object_root"]).resolve()
        else:
            object_root = (repo_root / "assets").resolve()
    report = run_coverage_gate(
        db=Path(args.db).resolve(),
        object_root=object_root,
        output=Path(args.output).resolve(),
        repo_root=repo_root,
    )
    logger.info("[V4][unit6.5] passed=%s missing=%s", report["passed"], report["missing"])
    print(
        json.dumps(
            {"ok": report["passed"], "output": Path(args.output).as_posix(), "missing": report["missing"]},
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
