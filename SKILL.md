---
name: video-agent
description: Generate a vertical product/demo video from a target website using CDP browser capture or frozen materials, visual-first planning, Minimax T2A voice/timing, video_project.json, FFmpeg rendering, and QA.
---

# Video Agent

Use this skill when the user provides a target website or asks for a short feature seeding, product demo, website showcase, or social media promo video from real website/material evidence.

## Required Reading

1. `docs/pipeline_v2_refactor.md` (see §4 for the `motion`/`transition_in` controlled-motion contract)
2. `cdp-capture/README.md` when browser interaction, screenshots, or recording is required
3. `rules/kehuanxiongmao-capture.md` for `https://kehuanxiongmao.com` or 柯幻熊猫
4. `rules/douyin-real-demo.md` for Douyin/Kuaishou/Reels/Shorts style output
5. `rules/vertical-browser-framing.md` for 9:16 website screenshots or result images
6. `references/copywriting-rules.md` and `references/copywriting-options.md` for 柯幻熊猫 copy

## V2 Outputs

- `image_resources.json`
- `assets/recordings/<label>/video.mp4` when a CDP operation recording is used
- `video_script.json`
- `audio/voice.mp3`
- `output/minimax/minimax_alignment.json`
- `subtitle_track.json`
- `video_project.json`
- `output/versions/<label>.mp4`
- `output/qa/contact_sheet.jpg`
- `output/reports/<label>_render_report.json`

## Execution

1. Initialize the case with `scripts/init_case.py`.
2. Gather real website/material evidence with CDP capture. For 柯幻熊猫, use the fixed `kehuanxiongmao` profile and capture entry, form, generation/loading, and final result states when logged in. Use CDP recording for the visible entry path when available.
3. Build or update `image_resources.json`; every visual must say what it proves and how it should be framed in 9:16.
4. Plan visually before writing narration. Decide whether each beat uses a website screenshot, operation state, or generated result image, then write the matching `video_script.json`.
5. Generate voice and native timing with `scripts/generate_voice_minimax.py`. The Minimax key stays local in `config/minimax.local.json` or `MINIMAX_API_KEY`.
   - Default Minimax speed is `1.2` unless the local config overrides it.
   - Request `subtitle_type=word`; keep the raw Minimax payload and normalize `timestamped_words` into word-level alignment segments.
6. Run `scripts/apply_asr_alignment.py` to map Minimax timing onto reviewed script segments.
7. For normal production, run `scripts/run_pipeline_mode.py` instead of manually chaining every post-script command.
   - `--mode draft`: fastest preview; keeps hard truth gates and rendering, skips GPT image, contact sheet, and render QA by default.
   - `--mode standard`: default daily mode; reuses unchanged voice/GPT/render outputs and runs voice QA, contact sheet, and render QA.
   - `--mode strict`: delivery gate; standard plus case hygiene and a denser contact sheet.
   - For website result videos, pass the current CDP registration receipt with `--receipt-id receipt_<capture_label>`. Do not run from demo cases or old case directories for a new video request.
8. If manual execution is needed, build and validate `video_project.json` with `scripts/build_video_project.py` and `scripts/validate_video_project.py --strict`.
9. Prepare GPT image keyframes with `scripts/prepare_gpt_image_keyframes.py` for standard/strict runs; draft runs may render from raw registered assets to get feedback faster.
10. Render with `scripts/render_simple_ffmpeg.py`; it produces the main FFmpeg video and appends the configured outro.
   - Subtitles are burned through ASS using the `douyin-live-smartclip` style: bottom centered, bold white text, black outline, height-based font size, and two-line wrapping.
   - Each `visual_track` event may carry `motion` (`hold` / `push_in` / `pull_out`, amount capped at `0.06`, anchor fixed at `center`) and `transition_in` (`cut` / `crossfade`). `build_video_project.py` fills conservative defaults automatically; do not hand-author values outside the whitelist. See `docs/pipeline_v2_refactor.md` §4.
   - Browser recordings use `layout=browser-recording-fit-width`: normal landscape recording, fitted to 1080px width, vertically centered. When `recording_camera_track.json` is registered, the renderer uses it for a virtual camera across `full_page`, `left_nav`, `feature_menu`, `left_form`, `generate_button`, and `result_area`.
11. Run contact-sheet and render QA before presenting a final video; `standard` and `strict` do this through the mode runner.

## Non-Negotiable Rules

- V2 uses `simple_ffmpeg` only. Do not route to HyperFrames.
- V2 uses `minimax_t2a` only. Do not route to voice clone or FunASR.
- `video_project.json` is the source of truth after it is built.
- Do not invent website states or generated results. Show only captured or supplied evidence.
- Do not press publishing, deleting, payment, or account-mutating actions without explicit user approval.
- For 柯幻熊猫, do not press `开始生成` unless logged-in state is verified and the user requested the generation workflow.
- For 柯幻熊猫, write login proof to `browser_materials.auth_state.logged_in=true`; V2 build/render refuses to continue without it.
- For 柯幻熊猫 feature seeding, show the entry path. Prefer a short CDP browser recording; if recording is unavailable, use sequential red-callout screenshots from home/`文生图` menu to the target feature and destination page.
- CDP recording must use the fixed `kehuanxiongmao` profile. Record only meaningful actions from entry to the real `开始生成` click, with all required inputs actually filled by `required: true` actions. Put `stopRecordingAfter: true` on that click; this only stops recording, and the same CDP task must continue after recording stops to wait for and save/export/crop the real result. Show final results from saved result images, not from a waiting result page recording.
- Register generation-trigger recordings with `scripts/register_cdp_recording.py --ends-after-generation-trigger` only when `metadata.json` proves post-recording actions ran and `results/` contains real result images from the same CDP chain. The registration step must update `assets/results/`, `image_resources.json`, and `generation_receipts.json`.
- Use CDP action semantics for short-video structure: `narration` for matched voice beats, `cameraFocus` for virtual camera targets, `required` for every mandatory field/control, and `stopRecordingAfter` only on the real generate trigger.
- Start every new website video in a fresh `cases/<new_case>` directory. Existing demo cases, example images, and old case assets are references only; they must not be used as the generated result for a new video.
- `run_pipeline_mode.py` must receive the current run's `--receipt-id` for any website video that claims or shows a real generated result. Without it, the runner refuses to render so old/demo result images cannot masquerade as fresh results.
- Final visuals must already be prepared and AI-verified. Function/process screenshots should be 9:16 captures; generated results must be saved images/crops/exports under `assets/results/`. The renderer width-fits images and does not perform local crop/zoom repair.
- The renderer merges consecutive `visual_track` events that share the same `layout`+`asset_ids` into one continuous shot with one uninterrupted motion sweep. Do not declare `crossfade` or a different `motion` between two such events; the validator rejects it.
- GPT image edits are for format, ratio, and layout optimization only. Prompts must preserve the original screenshot/result content and must not invent new UI, generated results, text, logos, or product details.
- Do not include the fixed outro in script, voice, subtitles, or visual beat planning; append it after the main video.
- Do not present a video as final if voice, subtitle timing, visual readability, or render QA fails.
- Use `draft` only for fast creative preview. Use `standard` for normal review and `strict` before treating a render as deliverable.
- Keep older output versions; use labels instead of overwriting accepted renders.
