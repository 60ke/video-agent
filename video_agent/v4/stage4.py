from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from video_agent.assets.v4 import AssetPlanResolver, LocalObjectStore, SQLiteAssetRepository
from video_agent.assets.v4.gap_policy import load_selection_config
from video_agent.assets.v4.usage_repository import AssetUsageRepository, SQLiteAssetUsageRepository
from video_agent.contracts.v4 import FrozenRegistrySnapshot, ResolvedAssetPlan, SceneSemanticPlan, Stage4SelectionConfig
from video_agent.io import load_json, load_model, sha256_file, sha256_json, utc_now, write_json_atomic
from video_agent.progress import get_logger
from video_agent.registries import CapabilityRegistryHub
from video_agent.runtime import RunContext


logger = get_logger()


@dataclass(frozen=True)
class V4Stage4Result:
    resolved_asset_plan: Path
    selection_decisions: Path
    derivation_requests: Path
    material_gaps: Path
    asset_resolution_session: Path
    asset_repository_snapshot: Path
    manifest: Path


def load_scene_semantic_plan(path: Path) -> SceneSemanticPlan:
    payload = load_json(path)
    if isinstance(payload, dict) and "payload" in payload and "scenes" not in payload:
        return SceneSemanticPlan.model_validate(payload["payload"])
    return SceneSemanticPlan.model_validate(payload)


def open_v4_repository(
    repo_root: Path,
    *,
    db: Path | None = None,
    object_root: Path | None = None,
    registry: CapabilityRegistryHub | None = None,
) -> SQLiteAssetRepository:
    config = load_json(repo_root / "config" / "assets.v4.json")
    database = db or (repo_root / config["database"]).resolve()
    objects = object_root or (repo_root / config["object_root"]).resolve()
    hub = registry or CapabilityRegistryHub.load(repo_root / "config" / "registries" / "v4")
    return SQLiteAssetRepository(database, LocalObjectStore(objects), hub)


def run_stage4_resolution(
    *,
    scene_plan: SceneSemanticPlan,
    repository: SQLiteAssetRepository,
    selection_config: Stage4SelectionConfig,
    run_seed: str,
    registry_snapshot_id: str,
    allow_fake_derivation: bool,
    run_id: str,
    usage: AssetUsageRepository | SQLiteAssetUsageRepository | None = None,
    repo_root: Path | None = None,
    run_dir: Path | None = None,
) -> ResolvedAssetPlan:
    session = repository.open_resolution_session()
    if allow_fake_derivation:
        resolver = AssetPlanResolver(repository.registry, usage=usage or AssetUsageRepository())
    else:
        resolver = AssetPlanResolver(
            repository.registry,
            usage=usage or AssetUsageRepository(),
            repo_root=repo_root,
            run_dir=run_dir,
        )
    try:
        return resolver.resolve(
            scene_plan,
            session=session,
            selection_config=selection_config,
            run_seed=run_seed,
            registry_snapshot_id=registry_snapshot_id,
            scene_plan_sha256=sha256_json(scene_plan),
            allow_fake_derivation=allow_fake_derivation,
            run_id=run_id,
        )
    except Exception:
        resolver.usage.abandon(run_id)
        raise


class V4Stage4Runner:
    def __init__(self, context: RunContext) -> None:
        self.context = context

    def run(
        self,
        *,
        run_seed: str = "default",
        allow_fake_derivation: bool = False,
        db: Path | None = None,
        object_root: Path | None = None,
        selection_config_path: Path | None = None,
    ) -> V4Stage4Result:
        started = time.perf_counter()
        scene_path = self.context.artifact("scene_semantic_plan.json")
        if not scene_path.is_file():
            raise FileNotFoundError(f"Stage4 requires scene_semantic_plan.json: {scene_path}")
        scene_plan = load_scene_semantic_plan(scene_path)
        selection_path = selection_config_path or (self.context.repo_root / "config" / "stage4_selection.v4.json")
        selection_config = load_selection_config(selection_path)
        registry_snapshot = self.context.artifact("capability_registry.snapshot.json")
        if not registry_snapshot.is_file():
            raise FileNotFoundError(f"Stage4 requires frozen capability registry: {registry_snapshot}")
        frozen_registry = load_model(registry_snapshot, FrozenRegistrySnapshot)
        registry_hub = CapabilityRegistryHub.from_snapshot(frozen_registry)
        registry_snapshot_id = frozen_registry.snapshot_id

        repository = open_v4_repository(
            self.context.repo_root,
            db=db,
            object_root=object_root,
            registry=registry_hub,
        )
        usage = SQLiteAssetUsageRepository(repository.db_path)
        try:
            plan = run_stage4_resolution(
                scene_plan=scene_plan,
                repository=repository,
                selection_config=selection_config,
                run_seed=run_seed,
                registry_snapshot_id=registry_snapshot_id,
                allow_fake_derivation=allow_fake_derivation,
                run_id=self.context.run_id,
                usage=usage,
                repo_root=self.context.repo_root,
                run_dir=self.context.run_dir,
            )
            used_assets = sorted(
                {slot.asset_ref for scene in plan.scenes for slot in scene.slots if slot.asset_ref}
            )
            used_groups = sorted(
                {slot.group_ref for scene in plan.scenes for slot in scene.slots if slot.group_ref}
            )
            asset_snapshot = repository.freeze(used_assets, used_groups)
            if asset_snapshot.snapshot_id != plan.used_assets_snapshot_id:
                raise RuntimeError("Stage4 used asset snapshot changed before artifact persistence")
            session_info = {
                "base_revision": plan.repository_base_revision,
                "pre_run_repository_fingerprint": plan.pre_run_repository_fingerprint,
                "post_run_repository_revision": plan.post_run_repository_revision,
                "post_run_repository_fingerprint": plan.post_run_repository_fingerprint,
            }
        finally:
            usage.close()
            repository.close()

        resolved_path = self.context.artifact("resolved_asset_plan.json")
        decisions_path = self.context.artifact("selection_decisions.json")
        derivations_path = self.context.artifact("derivation_requests.json")
        gaps_path = self.context.artifact("material_gaps.json")
        session_path = self.context.artifact("asset_resolution_session.json")
        asset_snapshot_path = self.context.artifact("asset_repository.snapshot.json")
        manifest_path = self.context.artifact("v4_stage4_manifest.json")
        write_json_atomic(resolved_path, plan)
        write_json_atomic(decisions_path, [item.model_dump(mode="json") for item in plan.selection_decisions])
        write_json_atomic(derivations_path, [item.model_dump(mode="json") for item in plan.derivation_requests])
        write_json_atomic(gaps_path, [item.model_dump(mode="json") for item in plan.material_gaps])
        write_json_atomic(session_path, session_info)
        write_json_atomic(asset_snapshot_path, asset_snapshot)
        input_fingerprint_payload = {
            "scene_plan_sha256": sha256_json(scene_plan),
            "selection_config_sha256": sha256_json(selection_config),
            "registry_snapshot_id": registry_snapshot_id,
            "registry_snapshot_file_sha256": sha256_file(registry_snapshot),
            "repository_base_revision": plan.repository_base_revision,
            "pre_run_repository_fingerprint": plan.pre_run_repository_fingerprint,
            "run_seed": run_seed,
            "allow_fake_derivation": allow_fake_derivation,
        }
        write_json_atomic(
            manifest_path,
            {
                "schema_version": "v4.stage4_manifest.1",
                "case_id": self.context.case.case_id,
                "run_id": self.context.run_id,
                "status": "resolved",
                "completed_at": utc_now(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "run_seed": run_seed,
                "allow_fake_derivation": allow_fake_derivation,
                "input_fingerprint": sha256_json(input_fingerprint_payload),
                "input_fingerprint_components": input_fingerprint_payload,
                "outputs": {
                    "resolved_asset_plan": resolved_path.relative_to(self.context.run_dir).as_posix(),
                    "selection_decisions": decisions_path.relative_to(self.context.run_dir).as_posix(),
                    "derivation_requests": derivations_path.relative_to(self.context.run_dir).as_posix(),
                    "material_gaps": gaps_path.relative_to(self.context.run_dir).as_posix(),
                    "asset_resolution_session": session_path.relative_to(self.context.run_dir).as_posix(),
                    "asset_repository_snapshot": asset_snapshot_path.relative_to(self.context.run_dir).as_posix(),
                },
            },
        )
        logger.info(
            "[V4][Stage4] 完成 case=%s run=%s scenes=%s elapsed=%.2fs",
            self.context.case.case_id,
            self.context.run_id,
            len(plan.scenes),
            time.perf_counter() - started,
        )
        return V4Stage4Result(
            resolved_asset_plan=resolved_path,
            selection_decisions=decisions_path,
            derivation_requests=derivations_path,
            material_gaps=gaps_path,
            asset_resolution_session=session_path,
            asset_repository_snapshot=asset_snapshot_path,
            manifest=manifest_path,
        )
