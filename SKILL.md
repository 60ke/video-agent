---
name: video-agent
description: Generate a vertical product/demo video from a target website using CDP screenshot capture or frozen materials, visual-first planning, Minimax T2A voice/timing, video_project.json, FFmpeg rendering, and QA.
---

# Video Agent

Use this skill when the user provides a target website or asks for a short feature seeding, product demo, website showcase, or social media promo video from real website/material evidence.

## Required Reading

1. `docs/pipeline_v2_refactor.md`
2. `cdp_screenshot_material_spec.md`
3. `cdp-capture/README.md` when browser login or screenshot material capture is required
4. `rules/kehuanxiongmao-capture.md` for `https://kehuanxiongmao.com` or 柯幻熊猫
5. `rules/douyin-real-demo.md` for Douyin/Kuaishou/Reels/Shorts style output
6. `rules/vertical-browser-framing.md` for 9:16 website screenshots or result images
7. `references/copywriting-rules.md` and `references/copywriting-options.md` for 柯幻熊猫 copy

## V2 Outputs

- `image_resources.json`
- `visual_plan.json`
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
2. Gather real website/material evidence. For 柯幻熊猫, use the fixed `kehuanxiongmao` CDP profile and refuse generation workflows when the logged-in state is unavailable.
3. Register site screenshots with `scripts/register_site_assets.py`; register saved result images with `scripts/register_result_assets.py` so each result carries feature and industry/scene labels.
4. Plan visuals before writing narration. Produce reviewed `visual_plan.json` first: each beat locks exact asset IDs, evidence binding, allowed claims, and forbidden claims.
5. Write `video_script.json` from the reviewed visual plan. Each script segment must reference `visual_beat_id`; its `preferred_asset_ids` must match that beat's `locked_asset_ids`.
6. Generate voice and native timing with `scripts/generate_voice_minimax.py`. The Minimax key stays local in `config/minimax.local.json` or `MINIMAX_API_KEY`.
   - Default Minimax speed is `1.5` unless local config overrides it.
   - Request `subtitle_type=word`; keep the raw Minimax payload and normalize `timestamped_words` into word-level alignment segments.
7. Run `scripts/build_subtitle_track.py` to map Minimax timing onto reviewed script segments.
8. For normal production, run `scripts/run_pipeline_mode.py` instead of manually chaining every post-script command.
   - `--mode standard`: default daily mode; **fully regenerates** voice, GPT image keyframes, render, voice QA, contact sheet, and render QA unless you pass `--cache` or `--reuse-gpt`.
   - `--mode draft`: fastest preview; skips GPT image and QA; may reuse cached voice/render with `--cache`.
   - `--mode strict`: delivery gate; same full-regeneration defaults as standard, plus case hygiene and a denser contact sheet.
   - `--gpt-image` defaults to `always`; use `never` only for intentional non-GPT previews.
9. If manual execution is needed, build and validate `video_project.json` with `scripts/build_video_project.py` and `scripts/validate_video_project.py --strict`.
10. Prepare GPT image keyframes with `scripts/prepare_gpt_image_keyframes.py` for standard/strict runs; draft runs may render from raw registered assets to get feedback faster.
11. Render with `scripts/render_simple_ffmpeg.py`; it produces the main FFmpeg video and appends the configured outro.
   - Subtitles are burned through ASS using the `douyin-live-smartclip` style: bottom centered, bold white text, black outline, height-based font size, and two-line wrapping.
   - Each `visual_track` event may carry `motion` (`hold` / `push_in` / `pull_out`, amount capped at `0.06`, anchor fixed at `center`) and `transition_in` (`cut` / `crossfade`). `build_video_project.py` fills conservative defaults automatically.
   - Website screenshot highlights are baked into GPT image prepared keyframes. Use `overlay_track` only for non-website dynamic cues when explicitly needed.
12. Run contact-sheet and render QA before presenting a final video; `standard` and `strict` do this through the mode runner.

## Non-Negotiable Rules

- V2 uses `simple_ffmpeg` only. Do not route to HyperFrames.
- V2 uses `minimax_t2a` only. Do not route to voice clone or FunASR.
- `video_project.json` is the source of truth after it is built.
- Do not invent website states or generated results. Show only captured or supplied evidence.
- Do not write narration before `visual_plan.json` locks the visual sequence for new cases. Script text must be derived from the locked beat's selected assets and allowed claims.
- Do not press publishing, deleting, payment, or account-mutating actions without explicit user approval.
- For 柯幻熊猫, do not press `开始生成` unless logged-in state is verified and the user requested the generation workflow.
- For 柯幻熊猫, write login proof to `browser_materials.auth_state.logged_in=true`; V2 build/render refuses to continue without it.
- For 柯幻熊猫 feature seeding, show the entry path with sequential prepared screenshots from homepage/`文生图` menu to the target feature and destination page.
- Start every new website video in a fresh `cases/<new_case>` directory. Existing demo cases, example images, and old case assets are references only; they must not be used as the generated result for a new video.
- `run_pipeline_mode.py` must receive the current run's `--receipt-id` for any website video that claims or shows a real generated result. Without it, the runner refuses to render so old/demo result images cannot masquerade as fresh results.
- Final visuals must already be prepared and AI-verified. Function/process screenshots should be 9:16 captures; generated results must be saved images/crops/exports under `assets/results/`. The renderer width-fits images and does not perform local crop/zoom repair.
- The renderer merges consecutive `visual_track` events that share the same `layout`+`asset_ids` into one continuous shot with one uninterrupted motion sweep. Do not declare `crossfade` or a different `motion` between two such events; the validator rejects it.
- GPT image edits are for format, ratio, and layout optimization only. Prompts must preserve the original screenshot/result content and must not invent new UI, generated results, text, logos, or product details.
- Do not include the fixed outro in script, voice, subtitles, or visual beat planning; append it after the main video.
- Do not present a video as final if voice, subtitle timing, visual readability, or render QA fails.
- Use `draft` only for fast creative preview. Use `standard` for normal review and `strict` before treating a render as deliverable.
- Keep older output versions; use labels instead of overwriting accepted renders.
