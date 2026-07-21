from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from video_agent.contracts.v4 import (
    AssetRecord,
    AssetGroupQuerySource,
    AssetQuerySource,
    ConfiguredAssetSource,
    EvidenceClass,
    GroupMemberSource,
    MaterialSlot,
    RelationFromInputSource,
    SceneInputSource,
    SceneSemanticPlan,
    SemanticScene,
)
from video_agent.contracts.v4.resolved_assets import (
    DerivationRequest,
    DerivationNarrativeContext,
    MaterialGap,
    ResolvedAssetPlan,
    ResolvedSceneAssets,
    ResolvedSlot,
    SelectionDecision,
    Stage4SelectionConfig,
    validate_resolved_asset_plan,
)
from video_agent.derivation.v4.capability_resolver import RegistryDerivationCapabilityResolver
from video_agent.registries import CapabilityRegistryHub

from .category_fallbacks import CATEGORY_INVENTORY_FALLBACKS
from .dependency_graph import topo_sort_scenes
from .derivation_orchestrator import (
    DerivationCapabilityResolver,
    DerivationExecutor,
    FakeDerivationExecutor,
    fulfill_derivation,
    infer_derivation_type,
    required_group_spec,
)
from .gap_policy import resolve_gap_action
from .group_resolver import GroupBindingTable, member_from_group
from .repository import AssetQuery, AssetResolutionSession, GroupQuery
from .selector import select_asset, select_group
from .stage4_errors import Stage4Error
from .usage_repository import AssetUsageRepository

_WEBSITE_ROLES = frozenset({"site_home", "feature_entry", "parameter_panel"})
_WEBSITE_EVIDENCE = frozenset({EvidenceClass.SOURCE, EvidenceClass.FAITHFUL})
# Adjacent selling points may reuse the same stocked page when inventory is thin.
_REUSABLE_INDEPENDENT_ROLES = frozenset({"site_home", "feature_entry", "parameter_panel", "other", "brand_logo"})


@dataclass
class AssetPlanResolver:
    registry: CapabilityRegistryHub
    usage: AssetUsageRepository = field(default_factory=AssetUsageRepository)
    repo_root: Path | None = None
    run_dir: Path | None = None
    capability_resolver: DerivationCapabilityResolver | None = None
    derivation_executor: DerivationExecutor | None = None
    material_gaps: list[MaterialGap] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.capability_resolver is None:
            self.capability_resolver = RegistryDerivationCapabilityResolver(
                self.registry,
                repo_root=self.repo_root,
            )
        if self.derivation_executor is None:
            if self.repo_root is not None:
                from video_agent.derivation.v4.executors import Stage5DerivationExecutor

                self.derivation_executor = Stage5DerivationExecutor(
                    self.repo_root,
                    self.registry,
                    run_dir=self.run_dir,
                )
            else:
                self.derivation_executor = FakeDerivationExecutor(registry=self.registry)

    def resolve(
        self,
        scene_plan: SceneSemanticPlan,
        *,
        session: AssetResolutionSession,
        selection_config: Stage4SelectionConfig,
        run_seed: str,
        registry_snapshot_id: str,
        scene_plan_sha256: str,
        allow_fake_derivation: bool = False,
        run_id: str = "stage4-run",
    ) -> ResolvedAssetPlan:
        scenes = topo_sort_scenes(scene_plan)
        self.material_gaps = []
        bindings = GroupBindingTable()
        resolved_outputs: dict[tuple[str, str], str] = {}
        independent_used: set[str] = set()
        independent_groups_used: set[str] = set()
        resolved_scenes: list[ResolvedSceneAssets] = []
        decisions: list[SelectionDecision] = []
        derivations: list[DerivationRequest] = []
        used_assets: set[str] = set()
        used_groups: set[str] = set()
        decision_seq = 1
        derivation_seq = 1
        previous_orientation: str | None = None

        for scene in scenes:
            inputs = self._resolve_inputs(scene, resolved_outputs)
            slot_results: list[ResolvedSlot] = []
            slot_assets: dict[str, str] = {}
            gallery_orientation: str | None = None

            for slot in scene.slots:
                resolved, decision, derivation, decision_seq, derivation_seq = self._resolve_slot(
                    scene=scene,
                    slot=slot,
                    inputs=inputs,
                    session=session,
                    selection_config=selection_config,
                    run_seed=run_seed,
                    bindings=bindings,
                    independent_used=independent_used,
                    independent_groups_used=independent_groups_used,
                    preferred_orientation=gallery_orientation or previous_orientation,
                    allow_fake_derivation=allow_fake_derivation,
                    decision_seq=decision_seq,
                    derivation_seq=derivation_seq,
                    run_id=run_id,
                )
                slot_results.append(resolved)
                if decision is not None:
                    decisions.append(decision)
                if derivation is not None:
                    derivations.append(derivation)
                if resolved.asset_ref:
                    slot_assets[slot.slot_id] = resolved.asset_ref
                    used_assets.add(resolved.asset_ref)
                    asset = session.get_asset(resolved.asset_ref)
                    if asset is not None:
                        previous_orientation = asset.orientation.value
                        if scene.visual_structure == "gallery" and gallery_orientation is None:
                            gallery_orientation = asset.orientation.value
                if resolved.group_ref:
                    used_groups.add(resolved.group_ref)

            outputs: dict[str, str] = {}
            for output in scene.outputs:
                asset_ref = slot_assets.get(output.bound_slot)
                if asset_ref is None:
                    raise Stage4Error(
                        "missing_scene_output",
                        f"output {output.output_name} bound to unresolved slot {output.bound_slot}",
                        scene_id=scene.scene_id,
                    )
                outputs[output.output_name] = asset_ref
                resolved_outputs[(scene.scene_id, output.output_name)] = asset_ref

            resolved_scenes.append(
                ResolvedSceneAssets(
                    scene_id=scene.scene_id,
                    inputs=inputs,
                    slots=slot_results,
                    outputs=outputs,
                )
            )

        snapshot = session.freeze_used(sorted(used_assets), sorted(used_groups))
        self.usage.mark_completed(run_id)
        plan = ResolvedAssetPlan(
            schema_version=1,
            run_seed=run_seed,
            scene_plan_sha256=scene_plan_sha256,
            repository_base_revision=session.base_revision,
            pre_run_repository_fingerprint=session.pre_run_repository_fingerprint,
            used_assets_snapshot_id=snapshot.snapshot_id,
            post_run_repository_revision=session.repository.current_revision(),
            post_run_repository_fingerprint=session.repository.repository_fingerprint(),
            registry_snapshot_id=registry_snapshot_id,
            group_bindings=bindings.bindings,
            scenes=resolved_scenes,
            selection_decisions=decisions,
            material_gaps=list(self.material_gaps),
            derivation_requests=derivations,
        )
        validate_resolved_asset_plan(plan)
        return plan

    def _resolve_inputs(
        self,
        scene: SemanticScene,
        resolved_outputs: dict[tuple[str, str], str],
    ) -> dict[str, str]:
        inputs: dict[str, str] = {}
        for inp in scene.inputs:
            key = (inp.from_scene, inp.from_output)
            asset_ref = resolved_outputs.get(key)
            if asset_ref is None:
                if inp.required:
                    raise Stage4Error(
                        "missing_scene_output",
                        f"required input {inp.input_name} missing from {inp.from_scene}.{inp.from_output}",
                        scene_id=scene.scene_id,
                    )
                continue
            inputs[inp.input_name] = asset_ref
        return inputs

    def _resolve_slot(
        self,
        *,
        scene: SemanticScene,
        slot: MaterialSlot,
        inputs: dict[str, str],
        session: AssetResolutionSession,
        selection_config: Stage4SelectionConfig,
        run_seed: str,
        bindings: GroupBindingTable,
        independent_used: set[str],
        independent_groups_used: set[str],
        preferred_orientation: str | None,
        allow_fake_derivation: bool,
        decision_seq: int,
        derivation_seq: int,
        run_id: str,
    ) -> tuple[ResolvedSlot, SelectionDecision | None, DerivationRequest | None, int, int]:
        source = slot.source
        kind = source.kind
        if kind == "scene_input":
            assert isinstance(source, SceneInputSource)
            asset_ref = inputs.get(source.input_name)
            if asset_ref is None:
                raise Stage4Error(
                    "missing_scene_output",
                    f"scene_input {source.input_name} not resolved",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
            decision = self._decision(
                decision_seq,
                scene,
                slot,
                {"kind": kind, "input_name": source.input_name},
                rank_mode="single",
                selection_scope="dependency_reuse",
                seed_material=f"{scene.scene_id}:{slot.slot_id}",
                selected_asset_ref=asset_ref,
            )
            return (
                ResolvedSlot(
                    slot_id=slot.slot_id,
                    status="resolved_asset",
                    asset_ref=asset_ref,
                    selection_decision_id=decision.decision_id,
                ),
                decision,
                None,
                decision_seq + 1,
                derivation_seq,
            )

        if kind == "configured_asset":
            assert isinstance(source, ConfiguredAssetSource)
            asset = session.configured_asset(source.config_key)
            if asset is None:
                raise Stage4Error(
                    "missing_configured_asset",
                    f"configured asset missing: {source.config_key}",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
            if asset.asset_role != slot.asset_role:
                raise Stage4Error(
                    "invalid_slot_source",
                    f"configured asset role mismatch: {asset.asset_role} != {slot.asset_role}",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
            decision = self._decision(
                decision_seq,
                scene,
                slot,
                {"kind": kind, "config_key": source.config_key},
                rank_mode="single",
                selection_scope="configured",
                seed_material=f"{scene.scene_id}:{slot.slot_id}",
                selected_asset_ref=asset.asset_ref,
            )
            self.usage.record_pending(run_id=run_id, scene_id=scene.scene_id, slot_id=slot.slot_id, asset_ref=asset.asset_ref)
            return (
                ResolvedSlot(
                    slot_id=slot.slot_id,
                    status="resolved_asset",
                    asset_ref=asset.asset_ref,
                    selection_decision_id=decision.decision_id,
                ),
                decision,
                None,
                decision_seq + 1,
                derivation_seq,
            )

        if kind == "group_member":
            assert isinstance(source, GroupMemberSource)
            group_ref = bindings.require_compatible(
                source.group_alias,
                group_type=source.group_type,
                pattern_id=source.pattern_id,
                category_id=slot.category_id,
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            )
            group = session.get_group(group_ref)
            if group is None:
                raise Stage4Error("incomplete_asset_group", f"bound group missing: {group_ref}", scene_id=scene.scene_id, slot_id=slot.slot_id)
            member = member_from_group(group, source.member_key, scene_id=scene.scene_id, slot_id=slot.slot_id)
            decision = self._decision(
                decision_seq,
                scene,
                slot,
                {"kind": kind, "group_alias": source.group_alias, "member_key": source.member_key},
                rank_mode="single",
                selection_scope="group_binding",
                seed_material=f"{scene.scene_id}:{slot.slot_id}",
                selected_asset_ref=member.asset_ref,
                selected_group_ref=group_ref,
            )
            return (
                ResolvedSlot(
                    slot_id=slot.slot_id,
                    status="resolved_group_member",
                    asset_ref=member.asset_ref,
                    group_ref=group_ref,
                    member_key=source.member_key,
                    selection_decision_id=decision.decision_id,
                ),
                decision,
                None,
                decision_seq + 1,
                derivation_seq,
            )

        if kind == "asset_query":
            assert isinstance(source, AssetQuerySource)
            return self._resolve_asset_query(
                scene=scene,
                slot=slot,
                session=session,
                selection_config=selection_config,
                run_seed=run_seed,
                independent_used=independent_used,
                preferred_orientation=preferred_orientation,
                allow_fake_derivation=allow_fake_derivation,
                decision_seq=decision_seq,
                derivation_seq=derivation_seq,
                run_id=run_id,
            )

        if kind == "asset_group_query":
            assert isinstance(source, AssetGroupQuerySource)
            return self._resolve_asset_group_query(
                scene=scene,
                slot=slot,
                source=source,
                session=session,
                selection_config=selection_config,
                run_seed=run_seed,
                bindings=bindings,
                independent_groups_used=independent_groups_used,
                allow_fake_derivation=allow_fake_derivation,
                decision_seq=decision_seq,
                derivation_seq=derivation_seq,
            )

        if kind == "relation_from_input":
            assert isinstance(source, RelationFromInputSource)
            return self._resolve_relation_from_input(
                scene=scene,
                slot=slot,
                source=source,
                inputs=inputs,
                session=session,
                selection_config=selection_config,
                run_seed=run_seed,
                bindings=bindings,
                allow_fake_derivation=allow_fake_derivation,
                decision_seq=decision_seq,
                derivation_seq=derivation_seq,
            )

        raise Stage4Error("invalid_slot_source", f"unsupported source kind: {kind}", scene_id=scene.scene_id, slot_id=slot.slot_id)

    def _resolve_asset_query(
        self,
        *,
        scene: SemanticScene,
        slot: MaterialSlot,
        session: AssetResolutionSession,
        selection_config: Stage4SelectionConfig,
        run_seed: str,
        independent_used: set[str],
        preferred_orientation: str | None,
        allow_fake_derivation: bool,
        decision_seq: int,
        derivation_seq: int,
        run_id: str,
    ) -> tuple[ResolvedSlot, SelectionDecision | None, DerivationRequest | None, int, int]:
        claims = self._slot_claims(scene, slot)
        query = AssetQuery(
            category_ids=(slot.category_id,) if slot.category_id else (),
            asset_roles=(slot.asset_role,),
            claims=tuple(claims),
            active_only=True,
        )
        candidates = session.query_assets(query)
        candidates = self._post_filter_evidence(candidates, slot.asset_role, session)
        unused = [item for item in candidates if item.asset_ref not in independent_used]
        if (
            not unused
            and candidates
            and slot.asset_role in _REUSABLE_INDEPENDENT_ROLES
        ):
            # Prefer unused inventory; if exhausted, allow reuse (e.g. single site_home).
            unused = list(candidates)
        candidates = unused
        fallback_category = CATEGORY_INVENTORY_FALLBACKS.get(slot.category_id or "")
        if not candidates and fallback_category:
            fallback_query = AssetQuery(
                category_ids=(fallback_category,),
                asset_roles=(slot.asset_role,),
                claims=tuple(claims),
                active_only=True,
            )
            candidates = session.query_assets(fallback_query)
            candidates = self._post_filter_evidence(candidates, slot.asset_role, session)
            unused = [item for item in candidates if item.asset_ref not in independent_used]
            if (
                not unused
                and candidates
                and slot.asset_role in _REUSABLE_INDEPENDENT_ROLES
            ):
                unused = list(candidates)
            candidates = unused
        if not candidates:
            return self._handle_gap(
                scene=scene,
                slot=slot,
                source_kind="asset_query",
                pattern_id=None,
                reason="no_candidate_asset" if slot.asset_role not in _WEBSITE_ROLES else "missing_source_asset",
                upstream=[],
                session=session,
                selection_config=selection_config,
                allow_fake_derivation=allow_fake_derivation,
                decision_seq=decision_seq,
                derivation_seq=derivation_seq,
                claims=claims,
            )
        selected, rank_mode, breakdown = select_asset(
            candidates,
            config=selection_config,
            run_seed=run_seed,
            seed_material=f"{scene.scene_id}:{slot.slot_id}",
            preferred_orientation=preferred_orientation,
            usage_counts=self.usage.counts(),
        )
        independent_used.add(selected.asset_ref)
        self.usage.record_pending(run_id=run_id, scene_id=scene.scene_id, slot_id=slot.slot_id, asset_ref=selected.asset_ref)
        decision = self._decision(
            decision_seq,
            scene,
            slot,
            {"kind": "asset_query", "category_id": slot.category_id, "asset_role": slot.asset_role, "claims": claims},
            rank_mode=rank_mode,
            selection_scope="independent",
            seed_material=f"{scene.scene_id}:{slot.slot_id}",
            selected_asset_ref=selected.asset_ref,
            candidate_asset_refs=[item.asset_ref for item in candidates],
            score_breakdown=breakdown,
        )
        return (
            ResolvedSlot(
                slot_id=slot.slot_id,
                status="resolved_asset",
                asset_ref=selected.asset_ref,
                selection_decision_id=decision.decision_id,
            ),
            decision,
            None,
            decision_seq + 1,
            derivation_seq,
        )

    def _resolve_asset_group_query(
        self,
        *,
        scene: SemanticScene,
        slot: MaterialSlot,
        source: AssetGroupQuerySource,
        session: AssetResolutionSession,
        selection_config: Stage4SelectionConfig,
        run_seed: str,
        bindings: GroupBindingTable,
        independent_groups_used: set[str],
        allow_fake_derivation: bool,
        decision_seq: int,
        derivation_seq: int,
    ) -> tuple[ResolvedSlot, SelectionDecision | None, DerivationRequest | None, int, int]:
        existing = bindings.get(source.group_alias)
        if existing is not None:
            bindings.require_compatible(
                source.group_alias,
                group_type=source.group_type,
                pattern_id=source.pattern_id,
                category_id=slot.category_id,
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            )
            group = session.get_group(existing)
            if group is None:
                raise Stage4Error("incomplete_asset_group", f"bound group missing: {existing}", scene_id=scene.scene_id, slot_id=slot.slot_id)
        else:
            query = GroupQuery(
                group_types=(source.group_type,),
                pattern_ids=(source.pattern_id,),
                category_ids=(slot.category_id,) if slot.category_id else (),
                required_member_keys=(source.member_key,),
                active_only=True,
            )
            groups = [group for group in session.query_groups(query) if group.group_ref not in independent_groups_used]
            if not groups:
                parents = session.query_assets(
                    AssetQuery(
                        category_ids=(slot.category_id,) if slot.category_id else (),
                        asset_roles=("parameter_panel",),
                        active_only=True,
                    )
                )
                parents = self._post_filter_evidence(parents, "parameter_panel", session)
                if not parents:
                    return self._handle_gap(
                        scene=scene,
                        slot=slot,
                        source_kind="asset_group_query",
                        pattern_id=source.pattern_id,
                        group_type=source.group_type,
                        member_key=source.member_key,
                        reason="missing_source_asset",
                        upstream=[],
                        session=session,
                        selection_config=selection_config,
                        allow_fake_derivation=allow_fake_derivation,
                        decision_seq=decision_seq,
                        derivation_seq=derivation_seq,
                        bindings=bindings,
                        retry=lambda: self._resolve_asset_group_query(
                            scene=scene,
                            slot=slot,
                            source=source,
                            session=session,
                            selection_config=selection_config,
                            run_seed=run_seed,
                            bindings=bindings,
                            independent_groups_used=independent_groups_used,
                            allow_fake_derivation=False,
                            decision_seq=decision_seq,
                            derivation_seq=derivation_seq + 1,
                        ),
                    )
                parent, _, _ = select_asset(
                    parents,
                    config=selection_config,
                    run_seed=run_seed,
                    seed_material=f"{scene.scene_id}:{slot.slot_id}:param-parent",
                )
                return self._handle_gap(
                    scene=scene,
                    slot=slot,
                    source_kind="asset_group_query",
                    pattern_id=source.pattern_id,
                    group_type=source.group_type,
                    member_key=source.member_key,
                    reason="incomplete_asset_group",
                    upstream=[parent.asset_ref],
                    session=session,
                    selection_config=selection_config,
                    allow_fake_derivation=allow_fake_derivation,
                    decision_seq=decision_seq,
                    derivation_seq=derivation_seq,
                    bindings=bindings,
                    retry=lambda: self._resolve_asset_group_query(
                        scene=scene,
                        slot=slot,
                        source=source,
                        session=session,
                        selection_config=selection_config,
                        run_seed=run_seed,
                        bindings=bindings,
                        independent_groups_used=independent_groups_used,
                        allow_fake_derivation=False,
                        decision_seq=decision_seq,
                        derivation_seq=derivation_seq + 1,
                    ),
                )
            group_assets = {
                member.asset_ref: asset
                for candidate in groups
                for member in candidate.members
                if (asset := session.get_asset(member.asset_ref)) is not None
            }
            group, rank_mode = select_group(
                groups,
                run_seed=run_seed,
                seed_material=f"{scene.scene_id}:{slot.slot_id}:{source.group_alias}",
                assets_by_ref=group_assets,
            )
            bindings.bind(source.group_alias, group, scene_id=scene.scene_id, slot_id=slot.slot_id)
            independent_groups_used.add(group.group_ref)
            decision = self._decision(
                decision_seq,
                scene,
                slot,
                {
                    "kind": "asset_group_query",
                    "group_alias": source.group_alias,
                    "pattern_id": source.pattern_id,
                    "member_key": source.member_key,
                },
                rank_mode=rank_mode,
                selection_scope="independent",
                seed_material=f"{scene.scene_id}:{slot.slot_id}",
                selected_group_ref=group.group_ref,
                candidate_group_refs=[item.group_ref for item in groups],
            )
            member = member_from_group(group, source.member_key, scene_id=scene.scene_id, slot_id=slot.slot_id)
            return (
                ResolvedSlot(
                    slot_id=slot.slot_id,
                    status="resolved_group_member",
                    asset_ref=member.asset_ref,
                    group_ref=group.group_ref,
                    member_key=source.member_key,
                    selection_decision_id=decision.decision_id,
                ),
                decision,
                None,
                decision_seq + 1,
                derivation_seq,
            )

        member = member_from_group(group, source.member_key, scene_id=scene.scene_id, slot_id=slot.slot_id)
        decision = self._decision(
            decision_seq,
            scene,
            slot,
            {"kind": "asset_group_query", "group_alias": source.group_alias, "reuse": True},
            rank_mode="single",
            selection_scope="group_binding",
            seed_material=f"{scene.scene_id}:{slot.slot_id}",
            selected_asset_ref=member.asset_ref,
            selected_group_ref=group.group_ref,
        )
        return (
            ResolvedSlot(
                slot_id=slot.slot_id,
                status="resolved_group_member",
                asset_ref=member.asset_ref,
                group_ref=group.group_ref,
                member_key=source.member_key,
                selection_decision_id=decision.decision_id,
            ),
            decision,
            None,
            decision_seq + 1,
            derivation_seq,
        )

    def _resolve_relation_from_input(
        self,
        *,
        scene: SemanticScene,
        slot: MaterialSlot,
        source: RelationFromInputSource,
        inputs: dict[str, str],
        session: AssetResolutionSession,
        selection_config: Stage4SelectionConfig,
        run_seed: str,
        bindings: GroupBindingTable,
        allow_fake_derivation: bool,
        decision_seq: int,
        derivation_seq: int,
    ) -> tuple[ResolvedSlot, SelectionDecision | None, DerivationRequest | None, int, int]:
        upstream = inputs.get(source.input_name)
        if upstream is None:
            raise Stage4Error(
                "missing_scene_output",
                f"relation_from_input missing input {source.input_name}",
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            )
        existing = bindings.get(source.group_alias)
        if existing is not None:
            bindings.require_compatible(
                source.group_alias,
                group_type=source.group_type,
                pattern_id=source.pattern_id,
                category_id=slot.category_id,
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            )
            group = session.get_group(existing)
            if group is None:
                raise Stage4Error("incomplete_asset_group", f"bound group missing: {existing}", scene_id=scene.scene_id, slot_id=slot.slot_id)
            if upstream not in {member.asset_ref for member in group.members}:
                raise Stage4Error(
                    "relation_not_bound_to_input",
                    f"bound group {existing} does not contain upstream {upstream}",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
        else:
            query = GroupQuery(
                group_types=(source.group_type,),
                pattern_ids=(source.pattern_id,),
                category_ids=(slot.category_id,) if slot.category_id else (),
                containing_asset_refs=(upstream,),
                required_member_keys=(source.member_key,),
                active_only=True,
            )
            groups = session.query_groups(query)
            if not groups:
                return self._handle_gap(
                    scene=scene,
                    slot=slot,
                    source_kind="relation_from_input",
                    pattern_id=source.pattern_id,
                    group_type=source.group_type,
                    member_key=source.member_key,
                    reason="relation_not_bound_to_input",
                    upstream=[upstream],
                    session=session,
                    selection_config=selection_config,
                    allow_fake_derivation=allow_fake_derivation,
                    decision_seq=decision_seq,
                    derivation_seq=derivation_seq,
                    bindings=bindings,
                    retry=lambda: self._resolve_relation_from_input(
                        scene=scene,
                        slot=slot,
                        source=source,
                        inputs=inputs,
                        session=session,
                        selection_config=selection_config,
                        run_seed=run_seed,
                        bindings=bindings,
                        allow_fake_derivation=False,
                        decision_seq=decision_seq,
                        derivation_seq=derivation_seq + 1,
                    ),
                )
            group_assets = {
                member.asset_ref: asset
                for candidate in groups
                for member in candidate.members
                if (asset := session.get_asset(member.asset_ref)) is not None
            }
            group, rank_mode = select_group(
                groups,
                run_seed=run_seed,
                seed_material=f"{scene.scene_id}:{slot.slot_id}:{source.group_alias}:{upstream}",
                assets_by_ref=group_assets,
            )
            bindings.bind(source.group_alias, group, scene_id=scene.scene_id, slot_id=slot.slot_id)
            member = member_from_group(group, source.member_key, scene_id=scene.scene_id, slot_id=slot.slot_id)
            decision = self._decision(
                decision_seq,
                scene,
                slot,
                {
                    "kind": "relation_from_input",
                    "input_name": source.input_name,
                    "group_alias": source.group_alias,
                    "pattern_id": source.pattern_id,
                    "upstream": upstream,
                },
                rank_mode=rank_mode,
                selection_scope="dependency_reuse",
                seed_material=f"{scene.scene_id}:{slot.slot_id}",
                selected_asset_ref=member.asset_ref,
                selected_group_ref=group.group_ref,
                candidate_group_refs=[item.group_ref for item in groups],
            )
            return (
                ResolvedSlot(
                    slot_id=slot.slot_id,
                    status="resolved_group_member",
                    asset_ref=member.asset_ref,
                    group_ref=group.group_ref,
                    member_key=source.member_key,
                    selection_decision_id=decision.decision_id,
                ),
                decision,
                None,
                decision_seq + 1,
                derivation_seq,
            )

        member = member_from_group(group, source.member_key, scene_id=scene.scene_id, slot_id=slot.slot_id)
        decision = self._decision(
            decision_seq,
            scene,
            slot,
            {"kind": "relation_from_input", "group_alias": source.group_alias, "reuse": True, "upstream": upstream},
            rank_mode="single",
            selection_scope="dependency_reuse",
            seed_material=f"{scene.scene_id}:{slot.slot_id}",
            selected_asset_ref=member.asset_ref,
            selected_group_ref=group.group_ref,
        )
        return (
            ResolvedSlot(
                slot_id=slot.slot_id,
                status="resolved_group_member",
                asset_ref=member.asset_ref,
                group_ref=group.group_ref,
                member_key=source.member_key,
                selection_decision_id=decision.decision_id,
            ),
            decision,
            None,
            decision_seq + 1,
            derivation_seq,
        )

    def _handle_gap(
        self,
        *,
        scene: SemanticScene,
        slot: MaterialSlot,
        source_kind: str,
        pattern_id: str | None,
        reason: str,
        upstream: list[str],
        session: AssetResolutionSession,
        selection_config: Stage4SelectionConfig,
        allow_fake_derivation: bool,
        decision_seq: int,
        derivation_seq: int,
        claims: list[str] | None = None,
        group_type: str | None = None,
        member_key: str | None = None,
        bindings: GroupBindingTable | None = None,
        retry: Callable[[], tuple[ResolvedSlot, SelectionDecision | None, DerivationRequest | None, int, int]] | None = None,
    ) -> tuple[ResolvedSlot, SelectionDecision | None, DerivationRequest | None, int, int]:
        if scene.no_asset or scene.visual_structure == "no_asset_transition":
            action = resolve_gap_action(
                selection_config,
                source_kind=source_kind,
                asset_role=slot.asset_role,
                pattern_id=pattern_id,
                scene=scene,
            )
            if action == "resolve_no_asset":
                return (
                    ResolvedSlot(slot_id=slot.slot_id, status="resolved_no_asset"),
                    None,
                    None,
                    decision_seq,
                    derivation_seq,
                )

        action = resolve_gap_action(
            selection_config,
            source_kind=source_kind,
            asset_role=slot.asset_role,
            pattern_id=pattern_id,
            scene=scene,
        )
        self.material_gaps.append(
            MaterialGap(
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
                category_id=slot.category_id,
                asset_role=slot.asset_role,
                source_variant=source_kind,
                required_group_type=group_type,
                required_pattern_id=pattern_id,
                required_member_key=member_key,
                upstream_asset_refs=list(upstream),
                claim_requirements=list(claims or []),
                reason_code=reason,
                derivation_allowed=action == "derive",
            )
        )
        if action in {"fail_missing_source", "fail_missing_config"}:
            code = "missing_source_asset" if action == "fail_missing_source" else "missing_configured_asset"
            raise Stage4Error(code, reason, scene_id=scene.scene_id, slot_id=slot.slot_id)
        if action == "resolve_no_asset":
            return (
                ResolvedSlot(slot_id=slot.slot_id, status="resolved_no_asset"),
                None,
                None,
                decision_seq,
                derivation_seq,
            )
        if action != "derive":
            raise Stage4Error("no_candidate_asset", f"unsupported gap action {action}", scene_id=scene.scene_id, slot_id=slot.slot_id)

        parent_refs = list(upstream)
        target_orientation: str | None = None
        for ref in parent_refs:
            asset = session.get_asset(ref)
            if asset is None:
                raise Stage4Error("derivation_failed", f"parent missing for derive: {ref}", scene_id=scene.scene_id, slot_id=slot.slot_id)
            target_orientation = target_orientation or asset.orientation.value
        if not parent_refs and source_kind != "asset_query":
            raise Stage4Error(
                reason if reason in {
                    "missing_source_asset",
                    "no_candidate_asset",
                    "incomplete_asset_group",
                    "relation_not_bound_to_input",
                } else "no_candidate_asset",
                "relationship derivation requires parent_asset_refs",
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            )

        assert self.derivation_executor is not None
        group_spec = None
        if source_kind in {"relation_from_input", "asset_group_query"}:
            if not pattern_id or not group_type or not member_key:
                raise Stage4Error(
                    "invalid_slot_source",
                    "group derivation requires pattern_id/group_type/member_key",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
            group_spec = required_group_spec(group_type, pattern_id, member_key)

        spoken_fields: list[str] = []
        registered_fields: list[str] = []
        callout_fields: list[str] = []
        if pattern_id == "parameter_callout_sequence":
            from .parameter_fields import parameter_narrative_fields

            parent = session.get_asset(parent_refs[0]) if parent_refs else None
            spoken_fields, registered_fields, callout_fields = parameter_narrative_fields(scene, parent)

        request = DerivationRequest(
            request_id=f"derivation://R{derivation_seq:04d}",
            scene_id=scene.scene_id,
            slot_id=slot.slot_id,
            derivation_type=infer_derivation_type(
                asset_role=slot.asset_role,
                pattern_id=pattern_id,
                parent_asset_refs=parent_refs,
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            ),
            category_id=slot.category_id,
            target_asset_role=slot.asset_role,
            required_group=group_spec,
            parent_asset_refs=parent_refs,
            evidence_ceiling="E2_semantic_derivative",
            narrative_context=DerivationNarrativeContext(
                scene_text=scene.text,
                anchor_phrase=slot.anchor_phrase,
                spoken_operation_fields=spoken_fields,
                registered_required_fields=registered_fields,
                callout_fields=callout_fields,
            ),
            target_orientation=target_orientation,
        )
        request, prepared, group = fulfill_derivation(
            request,
            session=session,
            resolver=self.capability_resolver,
            executor=self.derivation_executor,
            allow_fake=allow_fake_derivation,
            requires_stage5=selection_config.requires_stage5_registry,
            registry=self.registry,
        )

        if group_spec is not None:
            if group is None:
                raise Stage4Error(
                    "derivation_requery_failed",
                    "group derivation did not produce a group",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
            if bindings is not None and isinstance(slot.source, (RelationFromInputSource, AssetGroupQuerySource)):
                bindings.bind(slot.source.group_alias, group, scene_id=scene.scene_id, slot_id=slot.slot_id)
            if retry is None:
                raise Stage4Error(
                    "derivation_requery_failed",
                    "group derivation retry path missing",
                    scene_id=scene.scene_id,
                    slot_id=slot.slot_id,
                )
            resolved, decision, nested_request, next_decision, next_derivation = retry()
            return resolved, decision, request if nested_request is None else nested_request, next_decision, next_derivation

        derived = session.find_by_derivation_signature(prepared.derivation_signature)
        if derived is None or derived.asset_role != slot.asset_role:
            raise Stage4Error(
                "derivation_requery_failed",
                "derived asset did not satisfy original slot query after registration",
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
            )
        decision = self._decision(
            decision_seq,
            scene,
            slot,
            {"kind": source_kind, "derived": True, "signature": prepared.derivation_signature},
            rank_mode="single",
            selection_scope="independent" if source_kind == "asset_query" else "dependency_reuse",
            seed_material=f"{scene.scene_id}:{slot.slot_id}:derived",
            selected_asset_ref=derived.asset_ref,
        )
        return (
            ResolvedSlot(
                slot_id=slot.slot_id,
                status="resolved_asset",
                asset_ref=derived.asset_ref,
                selection_decision_id=decision.decision_id,
            ),
            decision,
            request,
            decision_seq + 1,
            derivation_seq + 1,
        )

    def _slot_claims(self, scene: SemanticScene, slot: MaterialSlot) -> list[str]:
        return sorted({claim.claim_id for claim in scene.claims if slot.slot_id in claim.supporting_slots})

    def _post_filter_evidence(
        self,
        candidates: list[AssetRecord],
        asset_role: str,
        session: AssetResolutionSession,
    ) -> list[AssetRecord]:
        if asset_role not in _WEBSITE_ROLES:
            return candidates
        return [
            item
            for item in candidates
            if item.evidence_class in _WEBSITE_EVIDENCE
            and (
                item.evidence_class == EvidenceClass.SOURCE
                or self._has_source_ancestor(item, session, set())
            )
        ]

    def _has_source_ancestor(
        self,
        asset: AssetRecord,
        session: AssetResolutionSession,
        visited: set[str],
    ) -> bool:
        if asset.asset_ref in visited or asset.lineage is None:
            return False
        visited.add(asset.asset_ref)
        for parent_ref in asset.lineage.parent_asset_refs:
            parent = session.get_asset(parent_ref)
            if parent is None:
                continue
            if parent.evidence_class == EvidenceClass.SOURCE:
                return True
            if self._has_source_ancestor(parent, session, visited):
                return True
        return False

    def _decision(
        self,
        seq: int,
        scene: SemanticScene,
        slot: MaterialSlot,
        query_contract: dict,
        *,
        rank_mode: str,
        selection_scope: str,
        seed_material: str,
        selected_asset_ref: str | None = None,
        selected_group_ref: str | None = None,
        candidate_asset_refs: list[str] | None = None,
        candidate_group_refs: list[str] | None = None,
        score_breakdown: dict[str, float] | None = None,
    ) -> SelectionDecision:
        return SelectionDecision(
            decision_id=f"decision://D{seq:04d}",
            scene_id=scene.scene_id,
            slot_id=slot.slot_id,
            query_contract=query_contract,
            candidate_asset_refs=candidate_asset_refs or [],
            candidate_group_refs=candidate_group_refs or [],
            hard_filter_counts={},
            rank_mode=rank_mode,  # type: ignore[arg-type]
            selection_scope=selection_scope,  # type: ignore[arg-type]
            seed_material=seed_material,
            score_breakdown=score_breakdown or {},
            selected_asset_ref=selected_asset_ref,
            selected_group_ref=selected_group_ref,
        )
