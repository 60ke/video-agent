# Agent Notes

- V3 is the only supported video pipeline.
- CDP produces clean screenshots and capture-time semantic metadata, not browser recordings or final video effects. Raw coordinates never enter runtime rendering.
- The Orchestrator owns the stage DAG; individual modules are not user-facing production entry points.
- `timing_lock.json` contains objective speech timing only. Visual actions belong to `visual_plan.json` and compile to absolute frames in `render_plan.json`.
- Keep local provider keys in ignored `config/*.local.json` files.
- Treat `assets/` as the externally curated boundary. Prefer same-feature E0/E1 assets; never let rejected, E2, or E3 material substantiate a factual product claim.
- Classify every narration span as an ActionScene before selecting assets, motion, or SFX. Derive concrete missing result evidence when reliable; reserve `light_sweep_fallback` for abstract bridges and unsupported claims.
- Fix reusable templates and compilers when a Golden Case reveals a problem; do not patch one case's rendered frames.
