# Agent Playbook

Use this playbook when a user asks the skill to generate or validate a vertical product/demo video.

The goal is not to improvise a one-off edit. The goal is to produce auditable artifacts that another agent can inspect, repair, and reuse.

Process assets are infrastructure, not the story. Capture a complete operation chain so the skill can be faster and safer next time, then select only the evidence that serves the requested short-video hook and claim.

Default evidence source: when a URL or website/product task is present, use Kimi WebBridge to capture real interaction and generated results. Static material folders are opt-in only; use them as primary evidence only when the user explicitly asks to use static resources, an existing material folder, or supplied assets.

## Default End-To-End Route

Use this route unless the user explicitly asks for only one stage.

1. Prepare case.
   - Resolve the skill root.
   - Create or verify the case directory.
   - Copy default voice prompt when `voice_config.prompt_audio_policy` is `default`.
   - Set default panda outro when `ending_track.policy` is absent or `default`.

2. Verify dependencies.
   - Kimi WebBridge is available for website/product tasks, or the user explicitly requested a static-materials workflow.
   - HyperFrames CLI is available.
   - ffmpeg and ffprobe are available.
   - FunASR imports or the configured ASR wrapper is available.
   - TTS or voice-clone endpoint is reachable.
   - Vision model capability is available to the agent.

3. Gather materials.
   - For website cases, use Kimi WebBridge to capture real browser evidence.
   - Do not replace WebBridge capture with static materials just because a material folder exists. Static materials may supplement the edit, but live browser evidence remains the source of truth unless the user explicitly requested a static-materials workflow.
   - For `https://kehuanxiongmao.com`, follow `rules/kehuanxiongmao-capture.md`: verify logged-in state and points > 100, capture the red-callout click path, fill demo inputs, generate when approved by the request, and save result exports/crops into the case directory.
   - For static-material cases, register supplied assets and inspect them with vision.
   - Save material descriptions, visible text, supported claims, and privacy notes.
   - Write `image_resources.json` so images are reusable by later agents without relying on filenames.
   - Keep all case artifacts and registered media inside the current skill project/case directory. If the user supplies an external folder, treat it as an import source only; copy/freeze usable files into `assets/static/` before writing manifests or rendering.
   - For product/demo videos, capture the real operation path before writing copy: entry screen, selected feature/category, input/control state, loading/generation state when available, result state, and any login/quota blocker.
   - Mark each material as `evidence_only`, `candidate_video_visual`, or `final_video_visual` during planning. Login, points, call-chain, and repeated form states are usually evidence-only unless the brief asks for a step-by-step walkthrough.
   - Classify each requested feature as `verified_result`, `verified_entry_only`, `blocked_login`, `blocked_quota`, `blocked_permission`, `unsafe_action`, or `unavailable`.
   - If the operation is blocked by quota/points, do not invent a result. Capture the blocker and ask for credits, supplied result material, or approval for a workflow-only preview.

4. Plan script and visuals.
   - Generate structured `video_script.json`, not only plain copy.
   - Bind every script segment to visual intent and candidate assets.
   - Do not turn the capture process itself into the video by default. Use the captured flow to validate claims, then write the shortest persuasive video that answers the user's brief.
   - Use copywriting references only as guidance; final render uses structured segments.
   - Every segment must map to captured evidence. If no evidence supports the line, rewrite the line or recapture.
   - For wide desktop browser captures, bind the segment to a named functional crop such as form fields, generate button, result gallery, or result image. Do not plan a full-page wide screenshot as the primary narrated visual.
   - For generated effect/result images, prefer whole-result display that fills the available width. Do not apply UI crop-focus rules unless the narration explicitly discusses a small detail.
   - Do not use generated photos, generic ecommerce mockups, emoji, or invented UI as product evidence.
   - When a requested category such as `电商` is shown, crop and narrate only that category state. Do not show unrelated category labels as equal subjects.

5. Generate voice and align subtitles.
   - Generate voice from reviewed text.
   - Measure audio duration with ffprobe.
   - Run FunASR after any speed fitting.
   - Use reviewed script text for subtitles and ASR timing for subtitle timestamps.

6. Build `video_project.json`.
   - Include voice, subtitle, visual, overlay, audio, ending, renderer, and QA tracks.
   - Keep fixed outro postprocess-only.
   - Ensure each visual event has layout reason and QA expectations.

7. Build and render HyperFrames.
   - Use only frozen local assets.
   - Preserve `video_project.json` timing.
   - Do not add unsupported claims or undeclared text.
   - Use stable holds and action-tied motion. Do not add arbitrary zoompan, breathing, jitter, floating cards, or motion that makes UI harder to read.
   - Treat `npx hyperframes lint`, `validate`, and `inspect` as hard gates. Do not continue to final render after a non-zero lint just because MP4 rendering can still produce a file.
   - Ensure primary scene clips on the same track do not overlap. Do not use small negative lead-ins for visual scene clips.
   - Root compositions need `data-start="0"`, declared local font faces, and no GSAP exit tween on `.clip` elements themselves.

8. Postprocess.
   - Append default panda outro after main video when declared.
   - Preserve outro audio.
   - Write versioned output paths.

9. Run QA.
   - Voice QA.
   - Subtitle QA.
   - Visual/layout QA.
   - Browser/material QA.
   - Render/package QA.

10. Report result.
   - Return final output only when QA passes.
   - If QA fails, return failures and repair actions instead of calling the render final.

## Task Routing

### New Website-To-Video Case

Read:

- `references/SPEC.md`
- `references/DEPENDENCIES.md`
- `references/SCHEMA.md`
- `references/QA.md`

Required artifacts:

- `website_knowledge.json`
- `feature_cards.json`
- `operation_recipes.json`
- `browser_materials.json`
- `image_resources.json`
- `generation_receipts.json`
- `video_script.json`
- `video_project.json`
- `output/reports/render_report.json`

Stop if:

- the site cannot be accessed or safely operated
- required claims cannot be supported by captured evidence
- private or sensitive data cannot be masked

### Static Material Folder Case

Read:

- `references/SCHEMA.md`
- `references/QA.md`

Required artifacts:

- `asset_manifest.json`
- `material_understanding.json`
- `video_script.json`
- `video_project.json`

Rules:

- Filenames are hints only.
- Use vision understanding before assigning assets to script segments.
- Do not render tiny full-page strips when crop-focus or multi-section is needed.

### Voice/Subtitles Repair

Read:

- `references/DEPENDENCIES.md`
- `references/QA.md`

Required checks:

- generated voice is playable
- ASR output exists
- high-risk terms are recognized
- subtitle end time does not exceed speech end time
- speed fitting stays within policy

Repair order:

1. Rewrite punctuation or split text.
2. Regenerate failed segment.
3. Crossfade or concat repaired segment.
4. Re-run FunASR.
5. Rebuild subtitle and visual timing.

### Layout Repair

Read:

- `references/QA.md`
- `references/SCHEMA.md`

Required checks:

- no black frames
- no meaningless empty panels
- no unreadably narrow UI screenshots
- no subtitle covering key UI/result content
- no flicker when the same asset continues

Repair order:

1. Change layout mode.
2. Change crop/focus region.
3. Split dense/tall images into sections.
4. Increase hold time or reduce scroll speed.
5. Rebuild affected scene and regenerate QA frames.

## Mandatory Acceptance Checklist

Before telling the user the video is final, verify:

- `video_project.json` exists and validates.
- Main video exists and is playable.
- Final video exists and is playable.
- ffprobe reports the expected resolution and audio stream.
- FunASR alignment exists for the generated main voice.
- Subtitles use ASR timing, not estimated timing.
- Voice tail is not clipped.
- Default outro appears only after the main generated video.
- No subtitle continues into the fixed outro unless explicitly declared.
- Contact sheet or snapshots were inspected.
- Render report records warnings and failures.
- No accepted output version was overwritten.
- For real-demo videos, the render report records `real_demo_status` and no product-result claim appears without captured or supplied result evidence.
- For category-focused videos, requested categories are visually dominant and unrelated categories are not presented as equal subjects.
- For Douyin videos, the contact sheet passes mobile readability: one dominant subject, no tiny full-page strips, no subtitle covering active UI/result content, and no artificial motion artifacts.
- For website/app scenes, the narrated subject remains inside the central safe region and no wide desktop screenshot is used as the primary visual without `crop-focus`, `multi-section`, or a result crop/export.

## Failure Policy

If a required dependency is missing, stop and report the missing dependency.

If browser evidence is insufficient, stop and ask for browser access or permission to use an explicitly supplied static-materials fallback.

If the user is logged in but has no credits/points, stop before any paid/quota-consuming action. Ask for permission/materials or produce only an explicitly labeled workflow preview.

If voice QA fails, do not continue to visual polish until the voice or text is repaired.

If visual/layout QA fails, return a repair plan and regenerate the affected scene before final delivery.

If render succeeds but QA fails, the output is a preview, not final.
