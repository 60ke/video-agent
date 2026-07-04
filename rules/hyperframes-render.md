---
name: hyperframes-render
description: Rules for rendering video-agent projects with HyperFrames.
---

# HyperFrames Render Rules

Use HyperFrames as the P0 renderer.

HyperFrames renders the main video from frozen local assets and `video_project.json`. It does not decide product claims, rewrite final narration, or replace browser evidence.

## Required Inputs

Before building HyperFrames, require:

```text
video_project.json
asset_manifest.json or browser_materials.json
audio/voice.wav
output/funasr/funasr_alignment.json
```

For preview-only work, missing voice/ASR may be allowed only when the output is clearly labeled preview.

## Source Of Truth

HyperFrames must follow:

- voice timing
- subtitle timing
- visual event start/end
- asset ids
- layout intent
- overlay declarations
- ending policy
- QA expectations

HyperFrames may choose:

- CSS composition details
- crop math
- callout shapes
- camera motion
- panel shadows/masks
- transition easing
- scene subdivision for readability

HyperFrames must not:

- invent unsupported claims
- add undeclared text overlays
- change timing without updating `video_project.json`
- hide unreadable UI behind decorative backgrounds
- render black gaps or flicker on same-asset continuity
- include the fixed panda outro inside the main composition

## Composition Rules

- Use local/frozen files only.
- Use `1080x1920` unless project meta says otherwise.
- Keep subtitles inside safe area.
- Keep important UI/result content outside the subtitle rail.
- Use crop-focus for dense desktop UI.
- Use multi-section or slow-scroll for tall screenshots only when scroll speed is readable.
- For dual panels, panel height should match actual displayed media height; do not leave large blurred/empty lower panels.
- If the same asset continues across adjacent visual events, hold continuity and avoid flash transitions.

## Default Outro Rule

The fixed panda outro is postprocess-only:

```text
assets/outro/default_panda_outro.mp4
```

Render the main HyperFrames video first. Append the outro with ffmpeg after main video timing and subtitle checks pass.

The outro must not affect:

- script segment durations
- voice duration
- FunASR subtitle timing
- visual-track timing

## Validation Commands

Run when a HyperFrames project exists:

```powershell
npx hyperframes lint
npx hyperframes validate
npx hyperframes inspect
```

Then render through the project script or wrapper:

```powershell
python scripts\render_hyperframes.py --case "<CASE_DIR>" --json
```

## QA Expectations

After render, create contact sheets or snapshots at:

- first frame
- each visual event start
- each visual event midpoint
- each visual event end
- outro join boundary
- final frame

Reject the render if:

- any media is missing
- any black gap appears at transitions
- UI is too small to understand
- dense screenshots are shown as unreadable strips
- extra white/yellow title text appears outside subtitles unless declared
- subtitle timing drifts from voice
- fixed outro starts before the generated main video ends

## Failure Rules

If HyperFrames CLI is unavailable, stop and report the missing dependency.

If HyperFrames renders but QA fails, mark the output preview-only and repair layout/timing before final delivery.

If Windows media extraction or symlink behavior fails, use ffmpeg postprocess for concat/mux rather than changing the project contract.
