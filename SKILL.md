---
name: video-agent
description: Generate a vertical product/demo video and platform-safe cover image from a target website using CDP screenshot capture or frozen materials, visual-first planning, concise subtitle timing, Minimax T2A voice/timing, video_project.json, registered programmatic image effects, GPT Image cover generation, FFmpeg rendering, cover first-frame prepending, and QA.
---

# Video Agent

Use this skill when the user provides a target website or asks for a short feature seeding, product demo, website showcase, social media promo video, or short-video cover image from real website/material evidence.

## Required Reading

1. `docs/pipeline_v2_refactor.md`
2. `docs/effects_pipeline.md`
3. `docs/cover_generation_strategy.md`
4. `docs/script_timing_constraints.md`
5. `cdp_screenshot_material_spec.md`
6. `cdp-capture/README.md` when browser login or screenshot material capture is required
7. `rules/kehuanxiongmao-capture.md` for `https://kehuanxiongmao.com` or 柯幻熊猫
8. `rules/douyin-real-demo.md` for Douyin/Kuaishou/Reels/Shorts style output
9. `rules/vertical-browser-framing.md` for 9:16 website screenshots or result images
10. `references/copywriting-rules.md` and `references/copywriting-options.md` for 柯幻熊猫 copy

## V2 Outputs

- `image_resources.json`
- `visual_plan.json`
- `video_script.json`
- `audio/voice.mp3`
- `output/minimax/minimax_alignment.json`
- `subtitle_track.json`
- `video_project.json`
- `video_project.effects.json` when registered image effects are applied
- `effect_asset_manifest.json` when GPT Image auxiliary effect assets are generated
- `output/versions/<label>.mp4`
- `output/cover/cover_plan.json` when a platform cover is planned
- `output/cover/cover_main.png` when a platform cover is generated
- `output/cover/cover_main_3x4_crop_preview.png` for cover safe-zone QA
- `output/qa/contact_sheet.jpg`
- `output/reports/<label>_render_report.json`
- `output/reports/subtitle_density_report.json` for subtitle/copy density QA
- `output/reports/cover_generation_report.json` when a cover is generated
- `output/reports/prepend_cover_report.json` when the cover is inserted as the video first frame

## Execution

1. Initialize the case with `scripts/init_case.py`.
2. Gather real website/material evidence. For 柯幻熊猫, use the fixed `kehuanxiongmao` CDP profile and refuse generation workflows when the logged-in state is unavailable.
3. Register site screenshots with `scripts/register_site_assets.py`; register saved result images with `scripts/register_result_assets.py` so each result carries feature and industry/scene labels.
4. Plan visuals before writing narration. Produce reviewed `visual_plan.json` first: each beat locks exact asset IDs, evidence binding, allowed claims, and forbidden claims.
5. Write `video_script.json` from the reviewed visual plan. Each script segment must reference `visual_beat_id`; its `preferred_asset_ids` must match that beat's `locked_asset_ids`.
   - For feature-seeding videos, follow `docs/script_timing_constraints.md`: 15-20s target, 10-14 preferred Chinese oral chars per segment, one conclusion plus one keyword per image.
6. Generate voice and native timing with `scripts/generate_voice_minimax.py`. The Minimax key stays local in `config/minimax.local.json` or `MINIMAX_API_KEY`.
   - Default Minimax speed is `1.5` unless local config overrides it.
   - Request `subtitle_type=word`; keep the raw Minimax payload and normalize `timestamped_words` into word-level alignment segments.
7. Run `scripts/build_subtitle_track.py` to map Minimax timing onto reviewed script segments.
8. Run `scripts/check_subtitle_density.py --subtitle <case>/subtitle_track.json --report <case>/output/reports/subtitle_density_report.json` before treating feature-seeding copy as final.
9. For normal production, run `scripts/run_pipeline_mode.py` to fully regenerate base tracks (voice/subtitle/project) from the reviewed plan and script. Keep cache reuse disabled for true fresh runs.
   - `--mode standard`: default daily mode; **fully regenerates** voice, GPT image keyframes, render, voice QA, contact sheet, and render QA unless you pass `--cache` or `--reuse-gpt`.
   - `--mode draft`: fastest preview for base tracks only; skips GPT image and QA; may reuse cached voice/render with `--cache`.
   - `--mode strict`: delivery gate; same full-regeneration defaults as standard, plus case hygiene and a denser contact sheet.
   - `--gpt-image` defaults to `always`; use `never` only for intentional non-GPT previews.
   - By default, existing registered result assets under `assets/results/` are allowed when no receipt is provided. Pass `--receipt-id` (and optionally `--require-receipt`) to bind only fresh receipt-matched results.
10. After base regeneration, use `scripts/render_with_effects.py` as the default final render entry for regular production. This is the canonical full-effects output path (not a side preview path).
   - It runs `apply_effect_plan.py` + `prepare_effect_assets.py` + `render_simple_ffmpeg.py` in sequence.
   - Use `--force-effect-plan --force-effect-assets` for no-reference/no-reuse effect regeneration.
   - Keep `--freeze-motion auto` unless a run explicitly needs `always`/`never`.
   - `render_simple_ffmpeg.py` performs the final encode and outro append.
   - Subtitles are burned through ASS using the `douyin-live-smartclip` style: bottom centered, bold white text, black outline, height-based font size, and two-line wrapping.
   - Each `visual_track` event may carry `motion` (`hold` / `push_in` / `pull_out`, amount capped at `0.06`, anchor fixed at `center`) and `transition_in` (`cut` / `crossfade`). `build_video_project.py` fills conservative defaults automatically.
   - Each `visual_track` event may also carry a registered `effect`: `drop_bounce`, `pop_in`, `zoom_pulse`, `tile_drop`, `radial_unfurl`, `wipe_reveal`, or `scan_overlay`.
   - Website screenshot highlights are baked into GPT image prepared keyframes. Use `overlay_track` only for non-website dynamic cues when explicitly needed.
11. If manual execution is needed, build and validate `video_project.json` with `scripts/build_video_project.py` and `scripts/validate_video_project.py --strict`, prepare GPT image keyframes with `scripts/prepare_gpt_image_keyframes.py`, apply registered image effects with `scripts/apply_effect_plan.py`, prepare `scan_overlay` auxiliary assets with `scripts/prepare_effect_assets.py` when needed, then render with `scripts/render_simple_ffmpeg.py`.
12. For a platform cover, use `scripts/render_with_cover.py --title <front-end-cover-title>`. It builds the cover plan, generates `cover_main.png`, and prepends the cover to the newest rendered video by default.
    - Cover titles must exactly match the front-end supplied `cover.title`; do not rewrite, shorten, translate, or invent title text.
    - Core cover content must stay inside the central 3:4 safe region. `output/cover/cover_main_3x4_crop_preview.png` is the required quick QA artifact.
    - Default video insertion is `--prepend-cover --cover-frame-count 1 --fps 30`, so the cover occupies the first `1/30s` frame. Use `--no-prepend-cover` to export only the standalone cover image.
13. Run contact-sheet, subtitle density QA, cover safe-zone QA, and render QA before presenting a final video; `standard` and `strict` do video QA through the mode runner.

## Non-Negotiable Rules

- V2 uses `simple_ffmpeg` only. Do not route to HyperFrames.
- V2 uses `minimax_t2a` only. Do not route to voice clone or FunASR.
- `video_project.json` or an explicit derivative such as `video_project.effects.json` is the source of truth after it is built.
- Do not invent website states or generated results. Show only captured or supplied evidence.
- Do not write narration before `visual_plan.json` locks the visual sequence for new cases. Script text must be derived from the locked beat's selected assets and allowed claims.
- Feature-seeding copy must be concise: one visual beat should carry one conclusion plus one keyword, not a full explanatory paragraph.
- Default script target is 15-20s. Avoid 30-40s explanatory scripts unless the user explicitly asks for a long version.
- Do not press publishing, deleting, payment, or account-mutating actions without explicit user approval.
- For 柯幻熊猫, do not press `开始生成` unless logged-in state is verified and the user requested the generation workflow.
- For 柯幻熊猫, write login proof to `browser_materials.auth_state.logged_in=true`; V2 build/render refuses to continue without it.
- For 柯幻熊猫 feature seeding, show the entry path with sequential prepared screenshots from homepage/`文生图` menu to the target feature and destination page.
- Start every new website video in a fresh `cases/<new_case>` directory. Existing demo cases, example images, and old case assets are references only; they must not be used as the generated result for a new video.
- The default full-process workflow starts from a new case and ends with effect-enabled final render output (`render_with_effects.py`).
- Regular production output is full-effects by default; do not treat effect rendering as optional preview-only behavior.
- By default, `run_pipeline_mode.py` allows existing registered result assets (from `assets/results/`) when no receipt is provided. For strict fresh-result binding, pass `--receipt-id` (and optionally `--require-receipt`) so only receipt-bound results are accepted.
- Final visuals must already be prepared and AI-verified. Function/process screenshots should be 9:16 captures; generated results must be saved images/crops/exports under `assets/results/`. The renderer width-fits images and does not perform local crop/zoom repair.
- The renderer merges consecutive `visual_track` events that share the same `layout`+`asset_ids` into one continuous shot with one uninterrupted motion/effect sweep. Do not declare `crossfade`, a different `motion`, or a different `effect` between two such events; the renderer rejects it.
- GPT image edits are for format, ratio, layout optimization, effect auxiliary overlays, and platform cover generation only. Prompts must preserve the original screenshot/result content and must not invent new UI, generated results, text, logos, or product details.
- Effect auxiliary GPT Image output is not a new evidence image; it is an overlay derived from the approved source asset.
- Cover generation must use the front-end supplied title exactly. If title accuracy cannot be verified, mark the cover as `review_required` instead of treating it as final.
- Cover main title, subject, product/person/result, and supporting subtitle must fit inside the central 3:4 safe region; outside that region only background extension, glow, gradient, outline, and decoration are allowed.
- Cover video insertion is first-frame only by default: one frame at 30fps. Do not insert a multi-second title card unless the user explicitly requests it.
- Do not include the fixed outro in script, voice, subtitles, or visual beat planning; append it after the main video.
- Do not present a video as final if voice, subtitle timing, subtitle density, visual readability, cover safe-zone/title accuracy, or render QA fails.
- Use `draft` only for fast creative preview. Use `standard` for normal review and `strict` before treating a render as deliverable.
- Keep older output versions; use labels instead of overwriting accepted renders.
