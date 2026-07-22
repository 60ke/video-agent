# Visual design

Visual design enriches each storyboard beat with a time-coded shot sequence. The unit is not an effect tag; it is a set of windows paced to the narration.

## Core rule

At the beginning of a beat, show only what the opening spoken cue needs. Reveal later UI labels, result cards, comparisons, or claims when the matching words are reached. Once the final reveal lands, hold it long enough to read.

The main failure modes are:

- slideshow: all content arrives immediately, then freezes;
- screensaver: every layer floats independently without narrative causality.

Stillness is valid. Front-loaded stillness is not.

## Scene blueprints

### `prompt-submit-result`

For an AI generation flow.

1. input or upload appears with its spoken cue;
2. option selection appears with its cue;
3. submit receives a click pulse;
4. waiting is shortened;
5. result gets a clean reveal and held read.

### `cursor-ui-demo`

For a product surface already populated. Frame the relevant UI, follow one meaningful action, and avoid wandering across unrelated navigation.

### `result-hero`

One registered image fills the primary visual area. Use a restrained push or crop reveal, then hold.

### `result-grid`

Reveal registered results one by one as categories or examples are named. Do not dump all images at frame start.

### `before-after-wipe`

Use only for explicit before/after language and two causally related registered assets.

### `kinetic-type`

Use when no truthful image evidence is required or available. Reveal short phrases on their spoken cues.

## Layout

Keep the product surface or hero result at least 40% of the usable canvas. Reserve the bottom caption band. Use centered, split-screen, asymmetric 60/40, grid, or layered depth according to beat function, not arbitrary variety.

## Motion

Use named intent such as `screen_push`, `cursor_fill`, `click_pulse`, `hero_reveal`, `grid_stagger`, `wipe_compare`, `text_pop`, and `hold`. Renderer implementation owns exact easing and pixels.
