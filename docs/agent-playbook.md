# Agent Playbook

Use this playbook when a user asks the skill to generate or validate a vertical product/demo video.

The goal is not to improvise a one-off edit. The goal is to produce auditable artifacts that another agent can inspect, repair, and reuse.

## Default End-To-End Route

Use this route unless the user explicitly asks for only one stage.

1. Prepare case.
   - Resolve the skill root.
   - Create or verify the case directory.
   - Copy default voice prompt when `voice_config.prompt_audio_policy` is `default`.
   - Set default panda outro when `ending_track.policy` is absent or `default`.

2. Verify dependencies.
   - Kimi WebBridge or accepted material folder is available.
   - HyperFrames CLI is available.
   - ffmpeg and ffprobe are available.
   - FunASR imports or the configured ASR wrapper is available.
   - TTS or voice-clone endpoint is reachable.
   - Vision model capability is available to the agent.

3. Gather materials.
   - For website cases, use Kimi WebBridge to capture real browser evidence.
   - For static-material cases, register supplied assets and inspect them with vision.
   - Save material descriptions, visible text, supported claims, and privacy notes.

4. Plan script and visuals.
   - Generate structured `video_script.json`, not only plain copy.
   - Bind every script segment to visual intent and candidate assets.
   - Use copywriting references only as guidance; final render uses structured segments.

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

## Failure Policy

If a required dependency is missing, stop and report the missing dependency.

If browser evidence is insufficient, stop and ask for access, screenshots, or a material folder.

If voice QA fails, do not continue to visual polish until the voice or text is repaired.

If visual/layout QA fails, return a repair plan and regenerate the affected scene before final delivery.

If render succeeds but QA fails, the output is a preview, not final.
