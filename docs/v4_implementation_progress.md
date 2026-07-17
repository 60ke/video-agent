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
| Stage 1: semantic Contract and AI runtime | in progress | Strict contracts, registry snapshot, validators, Stage 0 fixtures and structured dynamic prompts are implemented. Async runtime/traces/resume/orchestration remain. |
| Stage 2: capability and asset domain | pending | Formal design document required before implementation. |
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

## Verification Ledger

- `python -m pytest tests/test_v4_semantic_contracts.py -q`: PASS (7 tests).
- `python -m pytest tests/test_v4_prompts.py tests/test_v4_semantic_contracts.py -q`: PASS (10 tests).
- `python -m ruff check video_agent/contracts/v4 video_agent/registries video_agent/semantic tests/test_v4_semantic_contracts.py`: PASS.
- Full legacy suite currently has three unrelated baseline failures in `tests/test_assets.py`; they assert removed review metadata and the deleted brand-IP directory scan. These are tracked for the Stage 2 cutover rather than weakening the new Contract.
