---
name: video-agent
description: Produce editable Douyin product-demo videos from fixed copy or a production goal by coordinating product-truth inspection, scene planning, asset selection or capture, GPT Image derivation, MiniMax word timing, and native Jianying draft construction. Use when the task involves creating, repairing, resuming, or inspecting a Video Agent case.
---

# Video Agent

Use this Skill as the production controller. Inspect the current Case/Run first,
then call the smallest available tool that can move the Run forward. Do not treat
the Python production DAG as the Skill itself: it is a deterministic execution
backend used by the tools and by the secondary batch client.

## Workflow

Before the first production run on a machine, initialize local providers and
external tools with:

```powershell
python main.py agent setup
```

The wizard stores only ignored local configuration, validates the configured
Jianying Skill path, and reports whether the CDP auth state file exists. It
does not copy or print cookies. Use `--non-interactive` for a read-only
readiness check.

1. Inspect the repository, local provider configuration, Jianying capability, and
   current Run artifacts before making a decision.
2. Create or resume a Case. Freeze fixed copy exactly; for a goal, freeze the
   generated narration before TTS.
3. Build MiniMax speech with `subtitle_type=word`. Treat the resulting speech
   timing as immutable.
4. Plan scenes from the narration and product truth before selecting materials.
5. Resolve materials from the registered repository. When a required website state
   is missing, use CDP capture. When a registered derivation is allowed, use GPT
   Image and register its lineage before re-resolving the scene.
6. Compile Phrase Anchors, then choose scene-level edit intents and SFX intents.
7. Compile the deterministic edit blueprint and create a native Jianying draft.
8. Inspect the draft and delivery artifacts. Resume only the affected tool when a
   recoverable error is reported.

The local Tool Facade is invoked as:

```powershell
python main.py agent create-case --script <copy.txt> --json
python main.py agent inspect-context --case <case-dir> --json
python main.py agent session-inspect --run-dir <run-dir> --json
python main.py agent execute --case <case-dir> --run <run-id> --tool <tool-name> --json
```

The Agent selects one `--tool` per decision.  The command returns the stable
ToolResult envelope and appends the result to `agent_events.jsonl`; it does not
run an implicit downstream DAG.  The initial semantic frontend is an atomic
kernel shared by `freeze_narration`, `build_speech`, and `plan_scenes`, so the
first of those calls may materialize all five semantic frontend artifacts.  A
later call is a resume hit and does not call the provider again.

For a Jianying draft, the final tool call is:

```powershell
python main.py agent execute --case <case-dir> --run <run-id> `
  --tool build_jianying_draft --jianying-skill-root <skill-dir> --json
```

`capture_site` and `derive_assets` deliberately return `waiting_for_tool` when
no external provider adapter is connected.  The Skill must then invoke the CDP
or GPT Image provider, register its result, and resume the affected downstream
tool; the local facade never invents a capture or derivative.

Read these references only when needed:

- `references/tool_contracts.md` for Tool Result and Session contracts.
- `references/recovery_policy.md` for recoverable versus blocking errors.
- `references/scene_and_asset_taxonomy.md` for semantic scene and asset roles.
- `references/jianying_capabilities.md` for native editor capability boundaries.

## Hard boundaries

- The spoken phrase, subtitle Cue, visual focus, highlight, and SFX peak must use
  the same word-level Phrase Anchor.
- The Agent chooses semantic intent and the next tool. It never invents frame
  numbers, audio peaks, screenshot coordinates, or Jianying IDs.
- Timing, asset lineage, relationship validation, safe-area layout, and draft
  serialization remain deterministic and fail loudly.
- Every file already inside `assets/` is production-eligible; there is no review
  state or human-approval gate in the runtime.
- The only brand fallback is
  `assets/brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png`.
- Missing visuals use a registered derivation or `light_sweep_fallback`; never
  substitute an unrelated image.
- CDP captures facts and interaction events. It does not draw runtime callouts.
- GPT Image creates only registered derivatives with source lineage and a stable
  signature.
- Jianying consumes the compiled blueprint. It does not reinterpret copy or
  re-estimate timing.
- Never expose API keys, Cookies, database credentials, or host absolute paths to
  the Agent prompt or trace.

## Controllers

Interactive production is Skill-controlled and uses persisted Agent Session state.
`python main.py --script ...` and `--goal ...` remain secondary batch clients that
reuse the same Tool Contracts and artifacts. They must stop on a semantic or
product-truth gap instead of guessing.

Keep the deterministic kernel and the external `jianying-editor-skill` reusable;
do not add a second scene, asset, timing, or editor contract.
