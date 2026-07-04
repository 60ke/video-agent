# QA Rules

QA is a hard gate. A render is not final until voice, subtitle, visual, layout, and packaging checks pass.

## Voice QA

Required checks:

- generated voice exists and is playable
- voice duration matches planned main timeline
- voice-clone prompt audio is WAV when voice clone is used
- voice-clone prompt audio is about 5 seconds unless the selected API explicitly requires otherwise
- FunASR transcript exists
- subtitle timing comes from FunASR
- brand/product terms are recognized correctly
- high-risk terms are checked:
  - brand names
  - uncommon product names
  - mixed Chinese/English tokens such as `AI`
  - final slogans
- internal silence in a short slogan does not exceed policy

Recommended silence check:

```powershell
ffmpeg -i voice.wav -af silencedetect=noise=-35dB:d=0.12 -f null -
```

Reject or regenerate voice if:

- ASR misrecognizes a brand/product term
- the final slogan sounds one-word-at-a-time
- there are more than two internal silences longer than `0.12s` in a short slogan
- required speed fitting exceeds the project policy
- the voice tail would be clipped by the video duration
- prompt audio is an unsupported format such as M4A for the selected voice-clone API

Repair actions:

- convert prompt audio to `wav`, mono, `16000 Hz`
- regenerate only the failed segment
- normalize risky text with punctuation, for example `柯幻熊猫AI，是真的可以。`
- remove unnecessary Latin if it hurts delivery
- concatenate repaired segment with a short crossfade

Tool smoke checks:

```powershell
python -c "from funasr import AutoModel; print('funasr_import_ok')"
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 outputs/audio/voice.wav
```

## Subtitle QA

Required checks:

- subtitles use reviewed script text
- timing comes from ASR
- no subtitle remains after speech ends
- subtitle rail stays in safe area
- subtitle text is not clipped
- subtitle does not cover the main UI/result content

Recommended constraints:

- ordinary subtitle length: 8-18 Chinese characters
- long sentence should split at semantic pauses
- do not duplicate subtitle text as an additional title unless declared in overlay track

## Visual QA

Required checks:

- no black frames
- no missing media
- no large meaningless blank/blurred panels
- no frame where the main subject is too small to understand
- no flicker when the same asset is held across adjacent segments
- visual content matches the current subtitle
- website/app scenes are real captured states when a URL/frontend is available

Contact sheet:

- extract frames at event starts, midpoints, and ends
- inspect the first 3 seconds, every major transition, and final outro join
- any failed scene must be marked `needs_layout_revision`

## Layout QA

General rules:

- All generated videos are vertical mobile videos by default: `1080x1920`, `9:16`.
- Layout planning must happen before render, during material understanding and timeline planning.
- The main subject should occupy at least a reasonable share of the frame for mobile viewing.
- Decorative background is allowed, but should not dominate the scene.
- Empty space must be intentional and useful.
- UI screenshots must be readable or intentionally crop-focused.
- Captions must not obscure the core UI/result.

Reject a scene if:

- a tall source image appears as a narrow full-page strip
- a website/app screenshot is zoomed so far that the page purpose or key UI labels are lost
- a portrait result image has large side margins while the content could safely fill more width
- a blurred/background duplicate panel takes more visual weight than the actual material
- the chosen layout cannot be explained from subtitle meaning and asset role

Repair actions:

- rerun material understanding with explicit 9:16 layout review
- switch to `portrait-showcase` for near-9:16 result images
- switch to `crop-focus` for a named functional UI region
- switch tall pages to `multi-section` when the subtitle duration is too short for readable scrolling
- split one scene into sequential close-ups instead of equal-width unreadable panels

Dual/two-column rules:

```text
displayed_height = displayed_width * source_height / source_width
panel_height ~= displayed_height
```

Reject a dual layout if:

- image content fills only the top of a tall panel
- the lower panel is only blur/glass/empty background
- both images are too narrow to read
- one image is treated as primary but the layout presents both equally

Repair actions:

- resize panel height to media height
- switch to `main-plus-reference`
- split into sequential close-ups
- use crop-focus on each relevant section

Tall image rules:

- do not show dense tall pages as tiny full-height strips
- compute scroll speed before using `slow-scroll`
- if scrolling is too fast, split into `multi-section`
- hold at start and end long enough for comprehension
- for a segment shorter than 4 seconds, prefer `multi-section` over a full-length scroll
- if the image is a long marketing/detail page, show top, middle, and bottom sections as readable crops rather than shrinking the entire page

Wide website/app screenshot rules:

- full-width placement may still be unreadable in vertical video
- prefer portrait/mobile capture when available
- crop into functional area for form, result, gallery, editor, or detail page scenes
- use browser capture or frontend capture rather than static supplied screenshots when the live page is available
- every `crop-focus` scene must declare a focus region such as upload form, generate button, result gallery, editor canvas, or navigation/sidebar
- if the focus region is unknown, send the frame back to vision review instead of guessing with a center crop

## Browser Material QA

Required checks:

- `website_knowledge.json` exists
- each selected feature has URL evidence
- screenshots exist for pages used in video
- action events exist for browser operations
- result screenshot or result area exists for result claims
- no private user information, credentials, payment info, or sensitive account data appears
- failed browser steps include error screenshot and reason

## Render QA

Required checks:

- final video exists and is playable
- resolution is correct, usually `1080x1920`
- audio stream exists
- subtitles are visible
- no voice tail is clipped
- default ending appears after the main video when `ending_track.policy` is `default`
- optional/custom ending appears only if declared
- ending audio is preserved unless explicitly disabled
- video duration matches report
- output version does not overwrite previous accepted renders

Ending checks:

- fixed outro is not counted in voice duration or subtitle timing
- no subtitle continues into the fixed outro unless explicitly declared
- concat boundary has no black gap longer than one frame
- final duration equals main duration plus ending duration within tolerance

HyperFrames validation:

```powershell
npx hyperframes lint
npx hyperframes validate
npx hyperframes inspect
```

ffmpeg checks:

```powershell
ffprobe -v error -show_streams -show_format final.mp4
```

## QA Report

Each run should write:

```json
{
  "status": "passed",
  "checks": {},
  "warnings": [],
  "failures": [],
  "repair_actions": [],
  "contact_sheet": "output/qa/contact_sheet.jpg",
  "final_video": "output/versions/final.mp4"
}
```

If status is `failed`, the agent should not present the output as final.
