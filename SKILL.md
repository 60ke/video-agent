---
name: video-agent-v3
description: Build material-first 9:16 product demo videos with Minimax word timing, deterministic visual cues, platform-safe subtitles, controlled motion, and final MP4 QA.
---

# Video Agent V3

Use this repository when the user asks for a vertical feature-seeding, product-demo, or website-material video based on real screenshots and result images.

## Production Rules

1. Read `docs/video_agent_v3_final_design.md` and the case's `case.json`.
2. Capture website materials with `cdp-capture`; refuse generation actions when the required logged-in state is unavailable.
3. Build `assets/catalog.json` with `python -m video_agent catalog --assets assets --json`.
4. Write narration only from approved same-feature materials. Do not infer industries, fields, or product results that are not visible.
5. Run the single DAG with `python -m video_agent run --case cases/<case> --json`.
6. Inspect `qa_report.json`, `final/contact_sheet.jpg`, semantic hit frames, and the final MP4 before presenting it.

## Non-Negotiable

- Minimax uses speed `1.2` and `subtitle_type=word` unless the user changes the case.
- Word alignment must match lexical text exactly; punctuation omission is recoverable, text substitution is not.
- One-line subtitles only, at most 10 fullwidth units.
- UI fields are focused only when the spoken phrase matches a real CDP anchor. No unrelated fallback anchor.
- Website screenshots are never redrawn by GPT Image.
- GPT Image derivatives remain unreviewed until explicitly approved.
- E2/E3 assets cannot support factual claims.
- Render from one `render_plan.json`; do not recreate V2 project/effect/keyframe derivatives.
- Do not reintroduce `tile_drop`, `radial_unfurl`, or ordinary `drop_bounce`.
- Final delivery requires passed MP4 duration, dimensions, audio, loudness, subtitle, timeline, density, effect, and platform checks.

## Local Secrets

Keep `config/*.local.json` local. Never print keys or commit them.
