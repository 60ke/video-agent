# Video Agent V4 Implementation Progress

Last updated: 2026-07-20

## Authority

- Architecture: `video_agent_v4_architecture_framework_rev3_20260717.md`
- Stage 0 golden scenario: `video_agent_v4_stage0_golden_scenario_rev3_20260718.md`
- Stage 1 design: `video_agent_v4_stage1_semantic_contract_and_ai_runtime_design_20260717.md`
- Stage 2 design: `video_agent_v4_stage2_capability_and_asset_contracts_20260717.md`
- Stage 3 design: `video_agent_v4_stage3_repository_sqlite_migration_20260718.md`
- Stage 4 design: `video_agent_v4_stage4_dependency_selection_derivation_design_20260718.md`
- Stage 5 design: `video_agent_v4_stage5_executable_capability_and_derivation_design_20260718.md`
- Stage 6 design: `video_agent_v4_stage6_anchored_timing_compiler_and_remotion_adapter_design_20260718.md`
- Stage 7 design: `video_agent_v4_stage7_production_cutover_and_acceptance_design_20260720.md`

Stage 0 Rev3 is the semantic oracle and uses Stage 1 field names. If the oracle exposes a missing Contract capability, the Contract must be revised explicitly; runtime compatibility aliases are forbidden.

## Current Status

| Stage | Status | Notes |
|---|---|---|
| Baseline audit | complete | Public production entry remains V3; V4 Stages 1-6 are implemented behind explicit development entrypoints. |
| Stage 1: semantic Contract and AI runtime | runtime complete / production cutover conformance pending | Runtime, structured prompts, trace/replay, repair, routing and full registry freeze are implemented. Real-provider Stage 0 semantic conformance remains a Stage7 cutover gate. |
| Stage 2: capability and asset domain | complete | Typed dynamic registries, deterministic frozen snapshots, strict AssetRecord/Lineage/Group/Evidence contracts, registry-bound validation and Stage 1 projection are implemented. |
| Stage 3: repository, SQLite, ObjectStore and migration | complete | Repository, ObjectStore, import, snapshot (schema v4 with `evidence_class/claims`), audit and migration are implemented. |
| Stage 4: dependency, selection and derivation | complete | DoD closed: six slot sources, DAG, alias/dedup, gap policy, signature/`group_reuse`, atomic `register_derived_group`, parameter callout fields, E2 website filter, s001–s010 golden. Production wires Stage5 executor when `repo_root` set; Fake is test-only. |
| Stage 5: effect, SFX, voice and derivation registries | control plane complete / Stage6 timing wired | Registries/Voice/Derivation/Motion-SFX complete. Motion now consumes exact `AnchoredTimingPlan.scene_spans`; proportional fallback removed; Stage5 SFX no longer truncates distinct Anchors via `window_event_budget`. |
| Stage 6: semantic timing and compilation | complete / frozen | Real MiniMax Pass B closed on run `20260720_110920_904455` (145 tokens, 24.7s, 19 SFX, Remotion+FFmpeg final.mp4). Independent Git checkpoint: `a5130312`. |
| Stage 7: production cutover and acceptance | Units 0-6.5 passed / Unit7 script passed, goal open | Native speech, golden validators, Production Orchestrator, public CLI→V4. Unit6.5 gate passed (roles + reference_result_plan group). Live `--script` acceptance produced final/video.mp4 + cover.png. Remaining: `--goal` acceptance + Unit5+6 release tag. |

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
- `python -m pytest tests/test_v4_stage7_unit0_contracts.py -q`: PASS (8 tests), covering Production Case/Run, Goal Narration Prompt/route, BGM, Cover, QA and acceptance gates.
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
- [x] Stage6 evidence amendment freezes `evidence_class/claims` in each used-asset snapshot entry and includes them in snapshot hashing.
- [x] Import preflights files, topologically resolves local lineage, preserves explicit repository refs and reports orphaned copies.
- [x] Configured bindings enforce enabled keys, active targets and registry-declared target roles.
- [x] Repository audit checks objects, hashes, registry validity, lineage/group/supersede cycles and configured bindings.
- [x] Legacy dry-run follows the real transaction path and rolls back all repository writes.
- [x] Repaired authoritative editor relationships/workflow data pass a real `migrate-legacy --dry-run` without warnings or failures.

## Stage 6 review fixes (2026-07-20)

| Issue | Fix |
|---|---|
| P0 LightSweep empty black | Remotion `EffectStage` draws dedicated sweep/glow layer for `light_sweep` (no asset children required) |
| P0 BeforeAfter/GridReveal cuts | Comparison (and gallery when effect is multi-asset) compile as one scene-spanning clip with `asset_bindings` + `ordered_items`; export projects them onto one effect instance |
| P1 Resume never hits | `compiled_video_timeline_sha256` moved to `output_fingerprint*`; Resume compares stable `input_fingerprint` only |
| Subtitle hardcoded slots | Remotion `SubtitleTrack` reads `platform_profile.subtitle_*` from export; compile uses `get_profile` + PIL 56px font measure |
| Golden cleared SFX | Golden keeps Stage5 SFX intents; compile peak-aligns real wavs; default CI runs FFmpeg mix on lavfi black; Remotion+mix via `STAGE6_GOLDEN_RENDER=1` |
| Temp `_patch_*.py` | Deleted from repo root |

## Stage 6 Golden Acceptance Ledger (2026-07-20)

| Check | Result | Notes |
|---|---|---|
| s001–s010 compile path (§18 mappings) | PASS | Synthetic char-level `SpeechTimingLock` |
| Gallery yellow cues + distinct phrase hits | PASS | 文化墙 / 门头招牌 / 美陈 |
| s005 ≠ s002 gallery identity; s006–s008 inherit primary | PASS | Seeded Stage4 golden repo |
| s009 no_asset + s010 configured outro | PASS | LightSweep layer + configured outro |
| Multi-asset comparison export | PASS | `ordered_items` ≥ 2 on one effect instance |
| Platform subtitle profile export | PASS | `subtitle_top/lower` + `subtitle_font_px=56` |
| SFX peak compile + FFmpeg mix | PASS | Default CI: lavfi black + mix; Remotion path optional |
| Remotion `V4Timeline` + final mix | PASS | `STAGE6_GOLDEN_RENDER=1` |
| Stage0 Pass B MiniMax speech | PASS | run `20260720_110920_904455`; ledger `tests/fixtures/v4/stage6/pass_b_ledger.json` |

Commands:

```powershell
python -m pytest tests/test_v4_stage6_golden_compile.py::test_stage0_golden_s001_to_s010_compile -q
$env:STAGE6_GOLDEN_RENDER='1'; python -m pytest tests/test_v4_stage6_golden_compile.py::test_stage0_golden_remotion_render -q
```

## Stage0 Pass B (2026-07-20)

| Item | Result |
|---|---|
| Run | `cases/v4_stage0_golden_20260717/runs/20260720_110920_904455` |
| MiniMax SpeechTimingLock | 145 word tokens, 24732 ms; no `phrase_anchors` |
| Scene oracle | Rev3 fixture s001–s010 |
| s005 ≠ s002 gallery identity | `A0003` ≠ `A0002` |
| s006–s008 inherit primary | `source_result=A0003` |
| Compiled frames | 742 @ 30fps |
| SFX tracks | 19 |
| Final MP4 | `render/final.mp4` (~2.4 MB with mix) |
| Entrypoint | `python scripts/run_stage0_pass_b.py` |
| Status | `pass_b_closed` |

## Next Continuation Point

Stage7 Units 0–6.5 are complete; Unit7 script acceptance passed on branch. Next:
1. Run live MiniMax `--goal` production acceptance; freeze Unit7 acceptance ledger.
2. Create the final release tag covering Unit5+Unit6 cutover commits.
3. Keep BGM disabled until a real Profile is registered.
4. Optional: full V3 module purge after import-graph audit (Unit6 still partial).

### Unit7 script acceptance (2026-07-20)

| Field | Value |
|---|---|
| Case | `stage7_accept_script_20260720c` |
| Run | `20260720_145636_af70ac` |
| Final video | `final/video.mp4` (~3.5 MB, 729 frames) |
| Final cover | `final/cover.png` |
| Entrypoint | Stage0 golden script via `generate-video` + continue from assets |
