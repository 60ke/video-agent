# Video Agent V4 Implementation Progress

Last updated: 2026-07-18

## Authority

- Architecture: `video_agent_v4_architecture_framework_rev3_20260717.md`
- Stage 0 golden scenario: `video_agent_v4_stage0_golden_scenario_rev3_20260718.md`
- Stage 1 design: `video_agent_v4_stage1_semantic_contract_and_ai_runtime_design_20260717.md`
- Stage 2 design: `video_agent_v4_stage2_capability_and_asset_contracts_20260717.md`
- Stage 3 design: `video_agent_v4_stage3_repository_sqlite_migration_20260718.md`
- Stage 4 design: `video_agent_v4_stage4_dependency_selection_derivation_design_20260718.md`
- Stage 5 design: `video_agent_v4_stage5_executable_capability_and_derivation_design_20260718.md`
- Stage 6 design: `video_agent_v4_stage6_anchored_timing_compiler_and_remotion_adapter_design_20260718.md`

Stage 0 Rev3 is the semantic oracle and uses Stage 1 field names. If the oracle exposes a missing Contract capability, the Contract must be revised explicitly; runtime compatibility aliases are forbidden.

## Current Status

| Stage | Status | Notes |
|---|---|---|
| Baseline audit | complete | Current executable pipeline is V3. Stage 1 had design documents only. |
| Stage 1: semantic Contract and AI runtime | runtime complete / golden conformance partial | Runtime, structured prompts, trace/replay, repair and routing are implemented. Relation-pattern binding, full registry freeze and Stage 0 Rev3 semantic conformance remain open. |
| Stage 2: capability and asset domain | complete | Typed dynamic registries, deterministic frozen snapshots, strict AssetRecord/Lineage/Group/Evidence contracts, registry-bound validation and Stage 1 projection are implemented. |
| Stage 3: repository, SQLite, ObjectStore and migration | core complete / evidence snapshot amendment pending | Repository, ObjectStore, import, snapshot, audit and deterministic migration are implemented. Stage6 Unit 0 must add `evidence_class/claims` to `AssetRepositorySnapshotAsset`, bump snapshot schema and hash fixtures so Claim compilation never queries live SQLite. |
| Stage 4: dependency, selection and derivation | complete | DoD closed: six slot sources, DAG, alias/dedup, gap policy, signature/`group_reuse`, atomic `register_derived_group`, parameter callout fields, E2 website filter, s001–s010 golden. Production wires Stage5 executor when `repo_root` set; Fake is test-only. |
| Stage 5: effect, SFX, voice and derivation registries | control plane complete / timing integration pending | Registries/Voice/Derivation/Motion-SFX, signatures, handler fingerprints and Stage0 capability matrix are complete. Stage6 Unit 3 must reconnect Motion to exact `AnchoredTimingPlan.scene_spans`, remove proportional timing fallback and move frame-dependent SFX density arbitration out of Stage5. Effect handlers remain Stage6 Remotion stubs (`noop`). |
| Stage 6: semantic timing and compilation | design frozen / implementation pending | Design review gaps are closed. Begin with Unit 0 contracts, evidence-bearing repository snapshot amendment and fixtures before compiler or Remotion Adapter work. |
| Stage 7: planner cutover and verification | pending | Formal design document required before implementation. |

## Working Decisions

1. V4 contracts are isolated under `video_agent/contracts/v4`; V3 contracts remain untouched until cutover.
2. V4 AI nodes emit phrases copied from frozen narration. Python owns IDs outside each semantic object, registry validation, dependency validation and all timing.
3. Stage 0 Rev3 and its target fixtures use `scope_mode`, `order` and `visual_structure`. The former `scope`, `presentation_index`, `structure` and `continuity_group` fields are retired; runtime compatibility aliases will not be added.
4. Required root validation scripts (`test.txt` through `test4.txt`) remain local validation inputs and are not committed.
5. Structured semantic models default to `thinking=false`: these nodes transform a frozen contract and must spend their token budget on the JSON object. Model settings remain overrideable in `config/ai_runtime.v4.json`.
6. The Gateway appends the exact Pydantic-generated JSON Schema to every structured request. The effective prompt is fingerprinted and exported, so a stale shallow prompt cannot pass replay boundaries.
7. Stage 2 treats `active` repository assets as externally approved and removes review/approval state from the V4 domain. Legacy review fields remain migration input only.
8. Stage 2 keeps role/category IDs dynamic while preserving closed structural protocol values (`source_kind`, lifecycle, orientation and E0-E3 evidence IDs).
9. Registry JSON enters strict Pydantic contracts through JSON validation semantics; Python-side object construction remains strict and does not coerce enum or timestamp values.
10. Frozen registry restoration verifies outer IDs/versions, per-document hashes, aggregate hash and snapshot ID before exposing any entries.
11. `object_key` rejects Windows separators and host paths instead of normalizing them silently. Stage 3 migration is responsible for converting legacy paths deliberately.
12. Legacy `assets/catalog.json`, relationship manifests and review fields remain untouched Stage 3 migration inputs. The current unrelated local catalog regeneration is explicitly excluded from the Stage 2 commit.

## Verification Ledger

- `python -m pytest tests/test_v4_semantic_contracts.py -q`: PASS (7 tests).
- `python -m pytest tests/test_v4_prompts.py tests/test_v4_semantic_contracts.py -q`: PASS (10 tests).
- `python -m pytest tests/test_v4_ai_runtime.py tests/test_v4_prompts.py tests/test_v4_semantic_contracts.py -q`: PASS (13 tests).
- `python -m pytest tests/test_v4_semantic_stages.py tests/test_v4_semantic_contracts.py tests/test_v4_prompts.py tests/test_v4_ai_runtime.py -q`: PASS (17 tests).
- `python -m pytest tests/test_v4_stage1_orchestrator.py tests/test_v4_semantic_stages.py tests/test_v4_semantic_contracts.py tests/test_v4_prompts.py tests/test_v4_ai_runtime.py -q`: PASS (19 tests).
- `python -m pytest tests/test_v4_runtime_routing.py tests/test_v4_ai_runtime.py tests/test_v4_prompts.py tests/test_v4_semantic_stages.py tests/test_v4_stage1_orchestrator.py tests/test_v4_semantic_contracts.py -q`: PASS (23 tests).
- `python main.py v4-stage1 --help`: PASS.
- `python main.py v4-stage1 --case cases/v4_stage0_golden_20260717 --resume 20260717_211546_a4ed36`: PASS. Validated artifacts: `video_scope.json`, `scene_semantic_plan.json`; run elapsed 13.40s after prompt/routing stabilization.
- `python -m ruff check video_agent/contracts/v4 video_agent/registries video_agent/semantic tests/test_v4_semantic_contracts.py`: PASS.
- `python -m pytest tests/test_v4_registry_hub.py tests/test_v4_capability_assets.py -q`: PASS (19 tests).
- `python -m pytest tests/test_v4_registry_hub.py tests/test_v4_capability_assets.py tests/test_v4_stage1_orchestrator.py tests/test_v4_semantic_contracts.py tests/test_v4_prompts.py tests/test_v4_ai_runtime.py tests/test_v4_semantic_stages.py tests/test_v4_runtime_routing.py -q`: PASS (42 tests).
- `python -m ruff check video_agent/contracts/v4 video_agent/registries video_agent/assets/v4_validation.py video_agent/semantic tests/test_v4_registry_hub.py tests/test_v4_capability_assets.py tests/test_v4_stage1_orchestrator.py tests/test_v4_semantic_contracts.py tests/test_v4_prompts.py tests/test_v4_ai_runtime.py tests/test_v4_semantic_stages.py tests/test_v4_runtime_routing.py`: PASS.
- `python main.py v4-stage1 --case cases/v4_stage0_golden_20260717 --resume 20260717_211546_a4ed36`: PASS after Stage 2 registry cutover; validated Scope and Scene artifacts remain at the same run path.
- `python -m pytest tests/test_v4_stage3_repository.py -q`: PASS (15 tests), including video probing, snapshot restore, import lineage ordering/collision protection, configured-role validation and integrity audit.
- `python -m pytest tests/test_v4_*.py -q`: PASS (59 tests).
- `python -m ruff check video_agent/assets/v4 video_agent/cli.py video_agent/registries/hub.py tests/test_v4_stage3_repository.py`: PASS.
- `python main.py v4-assets --json migrate-legacy --dry-run`: PASS against the current authoritative asset inventory. Input fingerprint `7570211709036e8cc13e6229f3eef1264974c69db60541c2bbef362e898b7870`; editor process group `group://G0001`; warnings and failures are empty.

## Stage 2 Definition Of Done

- [x] Capability Registry Hub loads typed registry documents and validates duplicate IDs, normalized aliases, cross-references and handlers.
- [x] Disabled entries are hidden from active lookup but retained in frozen snapshots.
- [x] Frozen snapshot hashes are deterministic, content-sensitive and verified during restoration.
- [x] Stage 1 Agent-safe registry projection is generated from the Hub instead of a second hand-maintained registry.
- [x] AssetRecord enforces relative POSIX object keys, category identity, dimensions/orientation, lifecycle and source/lineage/evidence invariants.
- [x] AssetGroup enforces member identity/order and registry compatibility at the domain boundary.
- [x] V4 contracts contain no review, approval or visual-quality state.
- [x] Role and category IDs remain dynamic strings validated against the frozen registry boundary.
- [x] Stage 0 real-provider Scope and Scene Semantics execution still passes.

## Deferred TODOs

- [ ] **GPT Image 派生提示词质量**：`assets/derived/generated` 已清空；旧 `contextual_result_fill` / gallery preview / result_to_* 产物存在明显串类或语义错误（例如 `母婴服务_contextual_result_fill_*.png`）。当前优先推进 V4 架构，暂不修提示词。进入 Stage 4/5 派生执行前，必须重做 Derivation Prompt 模板与验收样例，禁止直接复用旧生成图或旧 prompt 指纹。

## Stage 3 Definition Of Done

- [x] SQLite repository, deterministic IDs, immutable registration and supersede behavior are implemented.
- [x] ObjectStore validates images and videos, rejects unsupported audio and verifies immutable hashes.
- [x] Active queries exclude descendants of superseded parents; historical lookup remains explicit.
- [x] Derivation signatures are unique and reusable.
- [x] Repository snapshots detect object/record/group tampering and restore from SQLite.
- [ ] Stage6 evidence amendment freezes `evidence_class/claims` in each used-asset snapshot entry and includes them in snapshot hashing.
- [x] Import preflights files, topologically resolves local lineage, preserves explicit repository refs and reports orphaned copies.
- [x] Configured bindings enforce enabled keys, active targets and registry-declared target roles.
- [x] Repository audit checks objects, hashes, registry validity, lineage/group/supersede cycles and configured bindings.
- [x] Legacy dry-run follows the real transaction path and rolls back all repository writes.
- [x] Repaired authoritative editor relationships/workflow data pass a real `migrate-legacy --dry-run` without warnings or failures.

## Next Continuation Point

Stage 5 control-plane DoD is closed; its exact timing integration remains Stage6 Unit 3. Next: implement Stage6 Unit 0 contracts, evidence-bearing repository snapshot amendment and fixtures.
- Effect Registry handlers remain `noop` stubs until Stage 6 wires Remotion.
- Full legacy suite currently has three unrelated baseline failures in `tests/test_assets.py`; they assert removed review metadata and the deleted brand-IP directory scan. These are tracked for the Stage 2 cutover rather than weakening the new Contract.
- Stage 5 closeout verification: `python -m pytest tests/test_v4_stage5_*.py tests/test_v4_stage4_*.py -q` and `python -m ruff check video_agent/v4/stage5.py video_agent/derivation/v4 video_agent/assets/v4/derivation_orchestrator.py`.
