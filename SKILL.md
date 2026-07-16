---
name: video-agent-v3
description: Build material-first 9:16 product demo videos with MiniMax word timing, ActionScene planning, cached GPT Image derivatives, Remotion motion, and FFmpeg audio mixing.
---

# Video Agent V3

Use this repository for vertical feature-seeding, product-demo, and website-material videos based on curated screenshots, references, result images, and workflow templates.

## Production Rules

1. Read `AGENTS.md`, `docs/architecture.md`, and the Case `case.json`.
2. Treat files already placed in `assets/` as externally curated inputs; machine checks do not perform visual approval.
3. Build the global catalog with `python -m video_agent catalog --assets assets --json`.
4. Use `script-lock` for approved copy or `ai_enabled=true` for API-generated Narration. Both paths must converge before speech synthesis.
5. Run the single DAG with `python -m video_agent run --case cases/<case> --json`.
6. Use `inspect` and the final MP4 to diagnose a run. Fix reusable planning, compile, or Remotion behavior instead of patching rendered frames.

## Non-Negotiable

- Spoken phrase, subtitle, visual hit, and assigned SFX share one word-level timing anchor.
- MiniMax must request `subtitle_type=word`; local configuration is the authority for model and voice.
- The canvas is 1080x1920 at 30 fps and uses the Douyin safe-area profile.
- Classify ActionScene before selecting material or motion.
- Strict causal scenes use registered relationships or contextual GPT Image derivation; never guess relationships from unrelated files.
- Missing visuals use `light_sweep_fallback`, not an unrelated brand image.
- Website emphasis comes from cached derivatives or effect metadata, never raw CDP-coordinate drawing at render time.
- Render from one `render_plan.json` through Remotion and FFmpeg.
- Do not reintroduce automatic Vision Critic, V2 compatibility, or global image-count limits.

## Local Secrets

Keep `config/*.local.json` local. Never print keys or commit them.
