# Video Agent

Agent-driven workflow for short vertical product/demo videos from real website evidence and prepared visual assets.

Pipeline V2 is the only supported path:

```text
CDP screenshot capture / static materials
-> assets/sites filename parsing + image_resources.json
-> locked visual_plan.json
-> evidence-bound video_script.json
-> Minimax T2A voice + word timing
-> subtitle_track.json
-> video_project.json
-> GPT image 9:16 keyframe optimization
-> FFmpeg image/sequence render + overlay_track + hard subtitles + outro
-> contact sheet + render QA
```

## Canonical Docs

Read these in order:

1. `SKILL.md` - agent-facing execution entry
2. `docs/pipeline_v2_refactor.md` - V2 rationale and architectural boundary
3. `cdp_screenshot_material_spec.md` - website screenshot naming, callout metadata, and registration contract
4. `cdp-capture/README.md` - CDP login and screenshot material capture
5. `rules/kehuanxiongmao-capture.md` - 柯幻熊猫 capture and generation rules
6. `rules/douyin-real-demo.md` - real-demo and short-video quality gates
7. `rules/vertical-browser-framing.md` - 9:16 website/result framing rules
8. `references/copywriting-rules.md` and `references/copywriting-options.md` - brand copywriting knowledge

## Local Secrets

Minimax credentials stay local in `config/minimax.local.json` or `MINIMAX_API_KEY`.
`config/*.local.json` is ignored by git.
If no speed is configured, Minimax T2A uses `speed=1.5` by default. Subtitle requests use `subtitle_type=word` and are converted into `output/minimax/minimax_alignment.json` before script-level subtitle tracks are built.

GPT image credentials stay local in `config/gpt_image.local.json` or `GPT_IMAGE_API_KEY`.
The default edit endpoint is OpenAI-compatible `/v1/images/edits`, using `gpt-image-2`.

## Visual Asset Policy

Final visuals are prepared before rendering. Function/process screenshots must be AI-verified 9:16 keyframes or registered site screenshots that can be prepared into 9:16. Generated-result visuals must be saved images, crops, or exports under `assets/results/`; website result page screenshots are evidence only and are rejected as final result visuals.

For website feature seeding, the entry path is part of the proof. Use sequential GPT-image prepared screenshots to show the route from homepage or product entry, to `文生图`, to the target feature, and then to the parameter page. CDP is a screenshot and coordinate-evidence producer only; website screenshot highlights are baked into prepared keyframes instead of renderer-side red boxes.

## Current Scripts

- `scripts/init_case.py` - create a V2 case scaffold
- `scripts/register_materials.py` - freeze static media into a case
- `scripts/register_site_assets.py` - register reusable `assets/sites` website screenshots into a case
- `scripts/register_result_assets.py` - register reusable or live generated result images by feature and industry/scene
- `scripts/apply_site_profile.py` - seed website knowledge from profiles
- `scripts/prepare_planner_context.py` - prepare visual-plan/script planner context
- `scripts/accept_planner_output.py` - validate AI planner JSON and write reviewed artifacts
- `scripts/create_voice_plan.py` - join reviewed script segments into voice text
- `scripts/generate_voice_minimax.py` - generate `audio/voice.mp3` and `output/minimax/minimax_alignment.json`
- `scripts/build_subtitle_track.py` - map Minimax timing onto reviewed script subtitles
- `scripts/check_voice_qa.py` - check speech density, terms, and silence
- `scripts/build_video_project.py` - assemble render-ready `video_project.json`
- `scripts/prepare_gpt_image_keyframes.py` - create AI-verified 1080x1920 keyframes from source screenshots/results
- `scripts/validate_video_project.py` - validate V2 case/project JSON
- `scripts/render_simple_ffmpeg.py` - render the final MP4 with FFmpeg and smartclip-style ASS subtitles
- `scripts/make_contact_sheet.py` - extract QA frames and contact sheet
- `scripts/render_qa.py` - run machine-checkable render QA
- `scripts/run_pipeline_mode.py` - run post-script production in `draft`, `standard`, or `strict` mode; `standard`/`strict` default to full regeneration and GPT image keyframes
- `scripts/check_case_hygiene.py` - check case and package hygiene

## Production Modes

After CDP/material capture, reviewed `visual_plan.json`, and reviewed `video_script.json`, prefer the mode runner. `--mode` defaults to `standard`, which **fully regenerates** voice, GPT image keyframes, and render by default. Use `--cache` / `--reuse-gpt` only when you explicitly want to reuse prior outputs. Use `--gpt-image never` only for draft-style previews inside standard mode.

```powershell
python scripts\run_pipeline_mode.py --case cases\<new_case> --label demo_v1 --json
python scripts\run_pipeline_mode.py --case cases\<new_case> --mode draft --label demo_draft --json
python scripts\run_pipeline_mode.py --case cases\<new_case> --mode strict --label demo_final --json
python scripts\run_pipeline_mode.py --case cases\<new_case> --label demo_cached --cache --reuse-gpt --json
```

For website result videos that claim a real generation result, pass the current receipt with `--receipt-id receipt_<capture_label>` so old demo images cannot be silently reused as fresh results.

## Minimal Command Flow

```powershell
python scripts\init_case.py --case cases\<new_case> --target-url "https://kehuanxiongmao.com/" --preferred-feature "活动美陈" --json
python scripts\apply_site_profile.py --case cases\<new_case> --profile kehuanxiongmao --json
node cdp-capture\bin\cdp-capture.js capture-material activity_meichen --mode visible
python scripts\register_site_assets.py --case cases\<new_case> --feature 活动美陈 --json
python scripts\register_result_assets.py --case cases\<new_case> --feature 活动美陈 --json
# capture/register any extra result images, then produce and accept visual_plan.json and video_script.json
python scripts\prepare_planner_context.py --case cases\<new_case> --stage visual_plan --json
python scripts\accept_planner_output.py --case cases\<new_case> --kind visual_plan --input <VISUAL_PLAN_JSON> --json
python scripts\prepare_planner_context.py --case cases\<new_case> --stage script --json
python scripts\accept_planner_output.py --case cases\<new_case> --kind script --input <SCRIPT_JSON> --json
python scripts\run_pipeline_mode.py --case cases\<new_case> --label demo_v1 --json
```

For manual project builds, after `video_project.json` exists:

```powershell
python scripts\prepare_gpt_image_keyframes.py --case cases\<new_case> --project cases\<new_case>\video_project.json --json
```
