# Video Agent Claude Adapter

This repository exposes the `video-agent` workflow as an Agent Skill. Read the
root `SKILL.md` and its `references/` before changing the pipeline. The Claude
adapter is a thin controller layer: use the existing Python Tool Facade and do
not create a second scene, asset, timing, or editor implementation.

## First run

Run the local setup wizard before production work:

```powershell
python main.py agent setup
```

It guides configuration for AI, MiniMax, GPT Image, the logged-in CDP profile,
and the external `jianying-editor-skill` directory. Credentials are entered
without being echoed and stored only in ignored `config/*.local.json` files.
The wizard does not copy or print cookies. If CDP login state is missing, run
the login command printed by the wizard and then rerun setup.

## Production control

Use the stable JSON tools, one checkpoint at a time:

```powershell
python main.py agent create-case --script <copy.txt> --json
python main.py agent inspect-context --case <case-dir> --json
python main.py agent execute --case <case-dir> --run <run-id> --tool <tool> --json
```

External CDP capture and GPT Image derivation are explicit provider handoffs.
Never invent a capture, derivative, timing anchor, or delivery path. Keep API
keys, cookies, local profiles, runs, and rendered media out of Git.
