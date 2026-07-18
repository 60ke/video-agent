# Video Agent V4 Implementation Progress

Last updated: 2026-07-18

## Authority

- Architecture: `video_agent_v4_architecture_framework_rev3_20260717.md`
- Stage 0 golden scenario: `video_agent_v4_stage0_golden_scenario_rev2_20260717.md`
- Stage 1 design: `video_agent_v4_stage1_semantic_contract_and_ai_runtime_design_20260717.md`
- Stage 2 design: `video_agent_v4_stage2_capability_and_asset_contracts_20260717.md`

When examples drift from the Stage 1 design, the Stage 1 strict Contract is authoritative. Golden fixtures preserve the Stage 0 meaning while using the final Stage 1 field names.

## Current Status

| Stage | Status | Notes |
|---|---|---|
| Baseline audit | complete | Current executable pipeline is V3. Stage 1 had design documents only. |
| Stage 1: semantic Contract and AI runtime | complete | Strict contracts, structured prompts, exact runtime schema injection, trace/replay, field repair, quality rebuild, routing and `V4Orchestrator` are implemented. Stage 0 real-provider execution produced validated Scope and Scene artifacts. |
| Stage 2: capability and asset domain | complete | Typed dynamic registries, deterministic frozen snapshots, strict AssetRecord/Lineage/Group/Evidence contracts, registry-bound validation and Stage 1 projection are implemented. |
| Stage 3: repository, SQLite, ObjectStore and migration | pending | Formal design document required before implementation. |
| Stage 4: dependency, selection and derivation | pending | Formal design document required before implementation. |
| Stage 5: effect, SFX, voice and derivation registries | pending | Formal design document required before implementation. |
| Stage 6: semantic timing and compilation | pending | Formal design document required before implementation. |
| Stage 7: planner cutover and verification | pending | Formal design document required before implementation. |

## Working Decisions

1. V4 contracts are isolated under `video_agent/contracts/v4`; V3 contracts remain untouched until cutover.
2. V4 AI nodes emit phrases copied from frozen narration. Python owns IDs outside each semantic object, registry validation, dependency validation and all timing.
3. The Stage 0 legacy example fields (`scope`, `presentation_index`, `structure`) are migrated in fixtures to Stage 1 fields (`scope_mode`, `order`, `visual_structure`). Runtime compatibility aliases will not be added.
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

## Next Continuation Point

Stage 3 is the first incomplete item. Write `docs/video_agent_v4_stage3_repository_sqlite_migration_20260718.md` before implementation, covering repository interfaces, SQLite schema, local ObjectStore, immutable registration/supersede behavior, deterministic migration from legacy catalogs/relationships/derived registries, idempotent reruns and rollback evidence.
- Full legacy suite currently has three unrelated baseline failures in `tests/test_assets.py`; they assert removed review metadata and the deleted brand-IP directory scan. These are tracked for the Stage 2 cutover rather than weakening the new Contract.
