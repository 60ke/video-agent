---
name: video-agent
description: Build editable Douyin product-demo videos with the repository's Agent Tool Facade and native Jianying draft backend.
---

# Video Agent Claude Skill

Use the repository root `SKILL.md` as the authoritative workflow and
`references/` for contracts and recovery. This file is only the Claude Code
discovery adapter; it must not duplicate pipeline rules.

Before the first run, execute:

```powershell
python main.py agent setup
```

Then use one structured tool command at a time:

```powershell
python main.py agent inspect-context --case <case-dir> --json
python main.py agent execute --case <case-dir> --run <run-id> --tool <tool-name> --json
```

The result is persisted in `agent_events.jsonl` and `agent_session.json`.
Respect the root timing contract, asset lineage, safe-area rules, and explicit
waiting states for CDP/GPT Image providers. Do not print or commit credentials,
cookies, host paths, runs, or rendered media.
