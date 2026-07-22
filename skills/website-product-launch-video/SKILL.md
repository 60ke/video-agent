---
name: website-product-launch-video
description: Turn a product URL, approved script, CDP recipe, and generated result images into a staged product launch or website demo video using MiniMax word timing, CDP recording, and Remotion.
---

# Website Product Launch Video

Use this skill for product launches, SaaS promos, website tours, feature reveals, and image-generation result showcases.

You are the orchestrator. Work inside one project directory and execute the stages in order. Each stage writes durable files; do not skip a gate by keeping important decisions only in chat.

```text
BRIEF.md
  -> capture/inventory.json
  -> STYLE.md
  -> STORYBOARD.md + SCRIPT.md + storyboard.json
  -> MiniMax word timing + subtitles
  -> visual_plan.json
  -> CDP recipe recordings
  -> Remotion
  -> renders/video.mp4
```

## Gate modes

`project.json.mode` is either `collaborative` or `autonomous`.

- `collaborative`: pause after Step 0 for brief approval, after Step 3 for storyboard/script approval, and before the final render in Step 6.
- `autonomous`: write the same decisions to the project files, state the stage summary, and continue without an approval pause.

Edits to an existing project resume from its durable artifacts. Do not re-run the brief interview or discard an approved storyboard unless the user asks for a structural rewrite.

## Non-negotiable rules

1. `SCRIPT.md` is the narration authority. Once audio starts, do not rewrite it.
2. MiniMax word timestamps are the timing authority for subtitles, beats, visual windows, and scene boundaries.
3. `storyboard.json` must preserve the exact concatenated narration from `SCRIPT.md`.
4. Website actions must bind to an existing CDP recipe. Never invent selectors at planning or render time.
5. Result scenes may only use files registered in `project.json.result_assets` and `capture/inventory.json`.
6. Story design chooses what to say and in what order. Visual design chooses how each beat develops over time. Do not merge these decisions into one opaque prompt.
7. Every visual beat is a time-coded sequence paced to spoken cues. Do not reveal the complete composition at the beginning and leave it frozen.
8. Remotion consumes `visual_plan.json`; it does not decide product claims, website actions, or asset truth.
9. Fix reusable recipes, storyboard contracts, alignment, or Remotion components. Do not patch rendered frames manually.

## Step 0 — Setup

Goal: create a durable project with a confirmed brief.

Initialize:

```bash
python -m agent_test init videos/<project> --title "<product>" --script "<approved narration if available>"
```

Required files:

- `project.json`: runtime configuration, recipe registry, result asset registry, TTS options.
- `BRIEF.md`: audience, goal, promise, proof, CTA, duration, aspect ratio, working mode.
- `SCRIPT.md`: narration bounded by `<!-- VO_START -->` and `<!-- VO_END -->`.
- `STYLE.md`: palette, typography roles, caption treatment, motion grammar.

Gate: `project.json`, `BRIEF.md`, `SCRIPT.md`, and `STYLE.md` exist; the brief states one audience, one promise, truthful proof, and one CTA. Collaborative mode requires approval.

## Step 1 — Capture and source inventory

Goal: establish which website operations and result images are allowed to appear.

Register CDP recipes under `project.json.recipes`. A recipe is either an inline JSON object or a path relative to the project directory. Register generated images under `project.json.result_assets`.

Build the canonical inventory:

```bash
python -m agent_test inventory videos/<project>
```

Output: `capture/inventory.json`.

A website recipe should contain a reproducible path such as open page, fill, select, click, wait for the current result, and hold. It must not treat old gallery items, placeholders, logos, or loading states as a fresh generated result.

Gate: `capture/inventory.json` exists; every website demonstration has a recipe id; every claimed result image is registered and exists.

## Step 2 — Visual system

Goal: establish one video-wide visual language before individual beats are animated.

Write `STYLE.md` from the product's real visual signals when available. It should define:

- canvas and safe area;
- palette roles, not arbitrary per-scene colors;
- display/body typography roles;
- caption treatment;
- browser framing;
- motion grammar and held-frame policy;
- negative rules, including no front-loaded slideshow and no independent screensaver motion.

Gate: `STYLE.md` is specific enough that two independent render implementations would produce recognizably related work.

## Step 3 — Storyboard and locked script

Goal: transform the brief and inventory into an ordered product story.

Read `../../references/story-design.md` and `../../references/project-contract.md`.

Write:

- `STORYBOARD.md`: human-readable proposal;
- `SCRIPT.md`: exact spoken narration;
- `storyboard.json`: machine-readable beats.

Choose one main arc:

- `pas`
- `future_pacing`
- `demo_loop`
- `bab`
- `feature_benefit_cascade`

Each beat must have one role:

- `hook`
- `pain_point`
- `product_intro`
- `feature_showcase`
- `benefit_highlight`
- `social_proof`
- `branding`
- `cta`

Each beat in `storyboard.json` must include `beat_id`, `role`, `voiceover`, `scene_kind`, `blueprint`, `transition_in`, and `visual_windows`. Website beats also include `recipe_id`; result beats include registered `asset_paths`.

The opening should speak in outcome language. Product features are evidence for the promise, not the promise itself. A website demo is normally a sequence such as input -> action -> response -> result -> benefit, not one undifferentiated browser clip.

Gate: the concatenated beat `voiceover` matches `SCRIPT.md`; all recipe ids and assets are registered; each beat has one clear job. Collaborative mode requires storyboard/script approval before audio.

## Step 3.1 — Audio and word timing

Goal: generate one complete narration track and make word timing authoritative.

```bash
python -m agent_test audio videos/<project>
```

Outputs:

- `work/voice/voice.mp3`
- `work/timing_lock.json`
- `work/subtitles.json`
- `work/audio_meta.json`

MiniMax must request word subtitles. Subtitle text, beat timing, and visual-window timing all derive from the returned tokens.

Gate: audio exists; valid tokens exist; subtitle cues are monotonic and fall within the audio duration.

## Step 4 — Time-coded visual plan

Goal: turn the approved storyboard into scenes and visual windows aligned to actual speech.

Read `../../references/visual-design.md`.

```bash
python -m agent_test plan videos/<project>
```

Output: `work/visual_plan.json`.

A visual window describes what enters when a spoken cue is reached. Use exact `cue` text when possible. Ratio windows are allowed only for a deliberate hold or non-verbal interval.

Supported scene kinds:

- `website_operation`
- `result_detail`
- `result_gallery`
- `before_after`
- `title_card`

Recommended local blueprints:

- `prompt-submit-result`
- `cursor-ui-demo`
- `result-hero`
- `result-grid`
- `before-after-wipe`
- `kinetic-type`

Gate: every beat aligned to word timing; every visual window is within its beat; reveals cover the spoken progression instead of landing entirely at the start.

## Step 5 — Build recordings and Remotion composition

Goal: execute only required website recipes and compile the visual plan.

```bash
python -m agent_test build videos/<project> --no-render
```

The build stage:

1. executes each referenced CDP recipe once;
2. writes MP4 recordings under `work/recordings/`;
3. stages only registered result images;
4. writes `work/remotion_props.json`;
5. maps each visual window to a Remotion `Sequence`.

Unlike HyperFrames' HTML frame workers, this implementation uses a small deterministic component library. The Agent decides story, scene kind, blueprint, assets, and timing; Remotion owns rendering mechanics.

Gate: required recordings exist, `remotion_props.json` exists, and every planned scene has its expected source.

## Step 6 — Check and render

Validate before final render:

```bash
python -m agent_test check videos/<project>
```

Collaborative mode previews the staged composition and asks for final approval. Autonomous mode reports the validation result and proceeds.

Render:

```bash
python -m agent_test build videos/<project>
```

Or execute the full workflow:

```bash
python -m agent_test run videos/<project>
```

Output: `videos/<project>/renders/video.mp4`.

Check:

- narration and storyboard text match;
- word timings are monotonic;
- website scenes use registered recipes;
- result scenes use registered assets;
- visual windows are word-aligned and contained by their beat;
- captions remain in the lower safe area and do not cover the main UI;
- browser waits are compressed or cut; results receive a readable hold;
- the final MP4 exists and matches the audio duration.

Gate: validation passes and the final MP4 exists.

## Project structure

```text
videos/<project>/
  BRIEF.md
  SCRIPT.md
  STORYBOARD.md
  STYLE.md
  project.json
  storyboard.json
  capture/inventory.json
  recipes/*.json
  assets/*
  work/
    audio_meta.json
    timing_lock.json
    subtitles.json
    visual_plan.json
    recordings/
    remotion_props.json
    report.json
  renders/video.mp4
```
