# Agent Tool Contracts

All Skill tools return a JSON envelope. The envelope is the protocol between the
Agent and the deterministic project code.

## Success

```json
{
  "ok": true,
  "tool": "resolve_materials",
  "tool_version": "1",
  "case_id": "video_...",
  "run_id": "20260727_...",
  "status": "completed",
  "artifacts": [],
  "gaps": [],
  "next_actions": [],
  "warnings": []
}
```

## Failure

```json
{
  "ok": false,
  "tool": "resolve_materials",
  "tool_version": "1",
  "case_id": "video_...",
  "run_id": "20260727_...",
  "status": "blocked",
  "error": {
    "code": "material_dependency_missing",
    "message": "编辑流程缺少 source_result",
    "recoverable": true
  },
  "next_actions": [
    {"action": "derive_assets", "capability_id": "result_to_editor_process"},
    {"action": "request_user_material"}
  ],
  "warnings": []
}
```

## First tool set

The first implementation exposes these tools. The names are stable; internal
Python modules may change behind them.

```text
inspect_context
create_case
freeze_narration
build_speech
plan_scenes
resolve_materials
capture_site
derive_assets
compile_anchors
plan_edit_intents
build_jianying_draft
inspect_delivery
```

The local CLI entrypoint for the atomic operations is:

```text
python main.py agent execute --case <case-dir> --run <run-id> --tool <name> --json
```

Case creation is separate because it creates the Case, Run, and Agent Session:

```text
python main.py agent create-case --script <copy.txt> --json
python main.py agent create-case --goal "..." --json
```

`freeze_narration`, `build_speech`, and `plan_scenes` share the existing
deterministic `V4Orchestrator.run_stage1` semantic-front-end kernel.  The
result includes a warning when that bundled kernel is materialized; this is an
explicit boundary, not an additional hidden DAG.

Every artifact path is relative to the repository or Case root. Tools may include
hashes, dimensions, IDs, and summaries, but never credentials or host paths.

## Agent Session

Each interactive Run stores:

```text
cases/<case>/runs/<run>/agent_session.json
cases/<case>/runs/<run>/agent_events.jsonl
```

`agent_session.json` records the current checkpoint, completed tools, pending gaps,
last call ID, and whether the Run is recoverable. `agent_events.jsonl` is append-only
and records tool calls, results, decisions, and timestamps.
