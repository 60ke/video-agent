# Video Agent V4 Implementation Progress

Last updated: 2026-07-17

## Authority

- Architecture: `video_agent_v4_architecture_framework_rev3_20260717.md`
- Stage 0 golden scenario: `video_agent_v4_stage0_golden_scenario_rev2_20260717.md`
- Stage 1 design: `video_agent_v4_stage1_semantic_contract_and_ai_runtime_design_20260717.md`

When examples drift from the Stage 1 design, the Stage 1 strict Contract is authoritative. Golden fixtures preserve the Stage 0 meaning while using the final Stage 1 field names.

## Current Status

| Stage | Status | Notes |
|---|---|---|
| Baseline audit | complete | Current executable pipeline is V3. Stage 1 had design documents only. |
| Stage 1: semantic Contract and AI runtime | complete | Strict contracts, structured prompts, exact runtime schema injection, trace/replay, field repair, quality rebuild, routing and `V4Orchestrator` are implemented. Stage 0 real-provider execution produced validated Scope and Scene artifacts. |
| Stage 2: capability and asset domain | in progress | Formal design completed in `video_agent_v4_stage2_capability_and_asset_contracts_20260717.md`; implementation is next. |
| Stage 3: asset resolution and derivation | pending | Formal design document required before implementation. |
| Stage 4: motion, SFX and voice assignment | pending | Formal design document required before implementation. |
| Stage 5: semantic timing and compilation | pending | Formal design document required before implementation. |
| Stage 6: render and delivery | pending | Formal design document required before implementation. |
| Stage 7: cutover and verification | pending | Formal design document required before implementation. |

## Working Decisions

1. V4 contracts are isolated under `video_agent/contracts/v4`; V3 contracts remain untouched until cutover.
2. V4 AI nodes emit phrases copied from frozen narration. Python owns IDs outside each semantic object, registry validation, dependency validation and all timing.
3. The Stage 0 legacy example fields (`scope`, `presentation_index`, `structure`) are migrated in fixtures to Stage 1 fields (`scope_mode`, `order`, `visual_structure`). Runtime compatibility aliases will not be added.
4. Required root validation scripts (`test.txt` through `test4.txt`) remain local validation inputs and are not committed.
5. Structured semantic models default to `thinking=false`: these nodes transform a frozen contract and must spend their token budget on the JSON object. Model settings remain overrideable in `config/ai_runtime.v4.json`.
6. The Gateway appends the exact Pydantic-generated JSON Schema to every structured request. The effective prompt is fingerprinted and exported, so a stale shallow prompt cannot pass replay boundaries.
7. Stage 2 treats `active` repository assets as externally approved and removes review/approval state from the V4 domain. Legacy review fields remain migration input only.
8. Stage 2 keeps role/category IDs dynamic while preserving closed structural protocol values (`source_kind`, lifecycle, orientation and E0-E3 evidence IDs).

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
- Full legacy suite currently has three unrelated baseline failures in `tests/test_assets.py`; they assert removed review metadata and the deleted brand-IP directory scan. These are tracked for the Stage 2 cutover rather than weakening the new Contract.
