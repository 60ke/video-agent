# Video Agent

Agent-driven website-to-video workflow for short vertical product/demo videos.

Pipeline V2 is the only supported path:

```text
CDP browser capture / static materials
-> optional CDP browser recording asset
-> image_resources.json
-> visual-first video_script.json
-> Minimax T2A voice + native alignment
-> video_project.json
-> GPT image 9:16 keyframe optimization
-> FFmpeg image concat + hard subtitles + outro
-> contact sheet + render QA
```

## Canonical Docs

Read these in order:

1. `SKILL.md` - agent-facing execution entry
2. `docs/pipeline_v2_refactor.md` - V2 rationale and architectural boundary
3. `cdp-capture/README.md` - CDP browser operation, recording, profile, and timeline contract
4. `rules/kehuanxiongmao-capture.md` - 柯幻熊猫 capture and generation flow
5. `rules/douyin-real-demo.md` - real-demo and short-video quality gates
6. `rules/vertical-browser-framing.md` - 9:16 website/result framing rules
7. `references/copywriting-rules.md` and `references/copywriting-options.md` - brand copywriting knowledge

## Local Secrets

Minimax credentials stay local in `config/minimax.local.json` or `MINIMAX_API_KEY`.
`config/*.local.json` is ignored by git.
If no speed is configured, Minimax T2A uses `speed=1.2` by default. Subtitle requests use `subtitle_type=word` and are converted into `output/minimax/minimax_alignment.json` before script-level subtitle tracks are built.

GPT image credentials stay local in `config/gpt_image.local.json` or `GPT_IMAGE_API_KEY`.
The default edit endpoint is OpenAI-compatible `/v1/images/edits`, using `gpt-image-2`.

## Visual Asset Policy

Final visuals are prepared before rendering. Function/process screenshots must be AI-verified 9:16 captures. Generated-result visuals must be saved images, crops, or exports under `assets/results/`; website result page screenshots are evidence only and are rejected as final result visuals.

For website feature seeding, the entry path is part of the proof. Prefer a short browser recording; otherwise use multiple red-callout screenshots that show the route from the product entry/menu into the target feature before the form/result appears.

CDP browser recordings are normal landscape captures. Register them into the case with `scripts/register_cdp_recording.py`; the renderer displays `browser-recording-fit-width` segments by fitting the recording to the 1080px video width and centering it vertically. If `recording_camera_track.json` is present, the renderer uses it as a virtual camera: full page first, then smooth focus on the left nav, feature menu, form, generate button, or result area according to real action timing.

Record only the useful operation path and stop right after the real generation trigger by setting `stopRecordingAfter: true` on that action. This only stops encoding the recording; the same CDP task must continue after recording stops to wait for and save/export/crop the real result under `assets/results/`. When registering with `--ends-after-generation-trigger`, `scripts/register_cdp_recording.py` requires metadata proof of post-recording result capture and copies result assets into `assets/results/`, `image_resources.json`, and `generation_receipts.json`.

## Current Scripts

- `scripts/init_case.py` - create a V2 case scaffold
- `scripts/register_materials.py` - freeze static media into a case
- `scripts/register_cdp_recording.py` - freeze a `cdp-capture` output directory into `assets/recordings/`
- `scripts/apply_site_profile.py` - seed website knowledge from profiles
- `scripts/build_image_resources.py` - merge browser/material evidence into reusable image resources
- `scripts/prepare_planner_context.py` - prepare visual-first planner context
- `scripts/accept_planner_output.py` - validate AI planner JSON and write reviewed artifacts
- `scripts/create_voice_plan.py` - join reviewed script segments into voice text
- `scripts/generate_voice_minimax.py` - generate `audio/voice.mp3` and `output/minimax/minimax_alignment.json`
- `scripts/apply_asr_alignment.py` - map Minimax timing onto reviewed script subtitles
- `scripts/check_voice_qa.py` - check speech density, terms, and silence
- `scripts/build_video_project.py` - assemble render-ready `video_project.json`
- `scripts/prepare_gpt_image_keyframes.py` - use GPT image edit to create AI-verified 1080x1920 keyframes from source screenshots/results
- `scripts/validate_video_project.py` - validate V2 case/project JSON
- `scripts/render_simple_ffmpeg.py` - render the final MP4 with FFmpeg and smartclip-style ASS subtitles
- `scripts/make_contact_sheet.py` - extract QA frames and contact sheet
- `scripts/render_qa.py` - run machine-checkable render QA
- `scripts/check_case_hygiene.py` - check case and package hygiene

## Minimal Command Flow

```powershell
python scripts\init_case.py --case cases\demo --target-url "https://kehuanxiongmao.com/" --preferred-feature "活动美陈" --json
python scripts\apply_site_profile.py --case cases\demo --profile kehuanxiongmao --json
node cdp-capture\bin\cdp-capture.js run cdp-capture\examples\task_activity_meichen.json
python scripts\register_cdp_recording.py --case cases\demo --recording-dir cdp-capture\output\<task-id> --label activity_meichen --feature-id activity_meichen --ends-after-generation-trigger --json
# capture/register any extra materials, then produce reviewed video_script.json
python scripts\create_voice_plan.py --case cases\demo --json
python scripts\generate_voice_minimax.py --case cases\demo --json
python scripts\apply_asr_alignment.py --case cases\demo --json
python scripts\build_video_project.py --case cases\demo --json
python scripts\prepare_gpt_image_keyframes.py --case cases\demo --json
python scripts\validate_video_project.py --case cases\demo --project cases\demo\video_project.gpt_image.json --strict --json
python scripts\render_simple_ffmpeg.py --case cases\demo --project cases\demo\video_project.gpt_image.json --label demo_v1 --json
python scripts\make_contact_sheet.py --case cases\demo --video cases\demo\output\versions\demo_v1.mp4 --json
python scripts\render_qa.py --case cases\demo --project cases\demo\video_project.gpt_image.json --video cases\demo\output\versions\demo_v1.mp4 --json
```
