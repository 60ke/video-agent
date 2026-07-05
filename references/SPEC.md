# Video Agent SPEC

## Purpose

Generate a vertical short-form feature seeding/product demo video from a target website, using an agent to understand the site, operate the browser, create narration, align subtitles, plan visuals, render with HyperFrames, and run quality checks.

The skill is not a black-box backend API. It is an agent workflow that coordinates local tools and produces auditable artifacts.

## P0 Scope

P0 must do:

- open and inspect a target website using Kimi WebBridge
- collect real browser screenshots, DOM/page text, and optionally short recordings
- classify operation evidence for requested features, including generated result, entry-only, login blocker, quota blocker, permission blocker, unsafe action, and unavailable states
- generate a structured script with semantic segments
- generate or receive TTS voice
- align subtitles with FunASR
- plan visual timing and layout into `video_project.json`
- render the main video with HyperFrames
- use ffmpeg for postprocess, optional intro/outro concat, frame extraction, and audio checks
- produce a render report and contact sheet

P0 does not need:

- multiple renderers
- BGM/SFX generation as required output
- database persistence
- public API service
- complete failure-retry orchestration
- live template editor

BGM, SFX, endings, and richer overlays are supported by the schema as optional tracks.

## Core Architecture

```text
user input
  -> Kimi WebBridge browser research
  -> website_knowledge.json
  -> feature_cards.json
  -> operation_recipes.json
  -> browser_materials.json
  -> vision asset understanding
  -> video_script.json
  -> voice.wav
  -> funasr_alignment.json
  -> video_project.json
  -> HyperFrames composition
  -> main.mp4
  -> ffmpeg postprocess / outro concat
  -> final.mp4
  -> render_report.json
```

## Browser Execution

P0 uses Kimi WebBridge with Local Agent.

The browser layer is responsible for:

- navigating pages
- reading visible page content
- interacting with upload, input, select, and button controls
- taking screenshots
- collecting DOM/page text when available
- recording action events
- capturing result images or result areas
- capturing login, quota/points, permission, or error blockers when a result cannot be produced

The browser layer is not the renderer. It freezes website evidence into files that HyperFrames can use.

For real product demos, the browser layer is the source of truth. HyperFrames may package, crop, annotate, and sequence captured evidence, but it must not invent product states or generated results.

## Rendering

P0 uses HyperFrames only.

HyperFrames is responsible for:

- building a deterministic HTML composition
- using screenshots/result images/recordings as media
- animating UI callouts, focus crops, result comparisons, and subtitle rail
- preserving timing from `video_project.json`

ffmpeg is responsible for:

- audio conversion and speed fitting
- silence detection
- intro/outro concat
- final muxing/compression
- frame extraction/contact sheets

## Source Of Truth

`video_project.json` is the single source of truth for the render.

It contains semantic tracks:

- `voice_track`
- `subtitle_track`
- `visual_track`
- `overlay_track`
- `audio_tracks`
- `ending_track`
- `qa_rules`
- `renderer_plan`

HyperFrames can choose creative HTML/CSS implementation details, but it cannot violate the project contract:

- no black frames
- no unexplained visual gaps
- no flicker when the same visual continues
- no unreadably narrow screenshots
- no large meaningless blank/blurred panels
- no subtitle timing based on estimates after voice exists
- no unsupported extra text outside subtitles or declared overlays
- no generated photo, generic mockup, emoji, or invented UI used as product evidence
- no product-result claim unless a real captured or user-supplied result asset exists
- no arbitrary zoompan, breathing, jitter, or floating motion that is not tied to a browser action or voiceover cue

## Workflow

1. Parse user input.
   - Required: `target_url`
   - Optional: `video_goal`, `duration`, `preferred_features`, `brand_profile`, `voice_config`, `ending_template`.

2. Research the website with Kimi WebBridge.
   - Capture homepage and likely feature pages.
   - Save screenshots and page text.
   - Identify login requirements and safe actions.
   - Identify quota/points requirements before any generation action.

3. Generate feature cards.
   - Each feature must have URL/page evidence.
   - Each feature must list visual moments suitable for video.
   - Each feature must declare `operation_status`: `verified_result`, `verified_entry_only`, `blocked_login`, `blocked_quota`, `blocked_permission`, `unsafe_action`, or `unavailable`.

4. Generate operation recipes.
   - Include action steps and selector/visual candidates when available.
   - Dangerous actions are forbidden: payment, deletion, publishing, external messaging, account changes.

5. Capture browser materials.
   - Collect screenshots/recordings/result areas tied to action events.
   - Store evidence in `browser_materials.json`.
   - If only an entry point is visible, store it as entry evidence only. Do not upgrade it into result evidence.
   - If the user is logged in but lacks credits/points, store the blocker and ask for permission/materials before planning a result demo.

6. Generate structured script.
   - Use the brand/copywriting knowledge base as guidance.
   - Output segments, not only plain copy.
   - Each segment should include stage, text, feature binding, visual intent, and material task.

7. Generate voice and align subtitles.
   - Run TTS or voice clone.
   - Run FunASR on the render audio.
   - Use reviewed script text for subtitle content and ASR timestamps for timing.

8. Build `video_project.json`.
   - Assign each subtitle segment to visuals.
   - Plan layout/framing with the QA rules.
   - Include optional overlays, intro/outro, and audio tracks.
   - For category-specific clips, use crop-focus on the requested category. Do not visually emphasize unrelated category labels.

9. Render with HyperFrames.
   - Use local/frozen assets only.
   - Build deterministic seekable animation.
   - Do not fetch external media at render time.

10. Postprocess with ffmpeg.
    - Append declared intro/outro if needed.
    - Normalize audio.
    - Extract QA frames/contact sheet.

11. Run QA.
    - If QA fails, write repair actions.
    - Do not call the output final when voice or layout QA fails.

## Relationship To Copywriting Docs

`references/copywriting-rules.md` and `references/copywriting-options.md` provide brand and copywriting constraints. They are not final output contracts.

If those docs say "output plain copy", that applies only to the copywriting draft step. The Script Director must convert copy into structured segments before rendering.

## Versioning

Every run must keep versioned outputs:

```text
output/versions/<label>.mp4
output/qa/<label>_contact_sheet.jpg
output/reports/<label>_render_report.json
```

Never overwrite an earlier accepted video.
