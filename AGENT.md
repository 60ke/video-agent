# Agent Notes

- V3 is the only supported video pipeline.
- CDP produces clean screenshots and callout coordinates, not browser recordings or final video effects.
- The Orchestrator owns the stage DAG; individual modules are not user-facing production entry points.
- `timing_lock.json` contains objective speech timing only. Visual actions belong to `visual_plan.json` and compile to absolute frames in `render_plan.json`.
- Keep local provider keys in ignored `config/*.local.json` files.
- Prefer same-feature E0/E1 assets. Never let unreviewed, rejected, E2, or E3 material substantiate a factual product claim.
- Fix reusable templates and compilers when a Golden Case reveals a problem; do not patch one case's rendered frames.
