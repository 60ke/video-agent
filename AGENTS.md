# Video-Agent Working Laws

## Timing Is a Hard Contract

For every semantic cue, the spoken phrase, subtitle cue, visual focus, and any
assigned SFX must resolve to the same word-level timing anchor. A render is not
acceptable when a cue is merely close by eye: the compiled frame anchors and
the actual audio peak must agree within the configured tolerance.

## Creative Rules

- Effects declare their own readable-settle and minimum-scene requirements.
  Do not introduce global scene-duration or image-count limits as a proxy for
  quality.
- Every file under `assets/` is already inside the project production boundary.
  Runtime checks only verify technical integrity; there is no review-state gate
  and no `human_approved`/`reviewed` asset workflow.
- The official brand fallback is only `assets/brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png`.
  Do not use a generic panda IP asset as a missing-scene fallback.
- The Douyin canvas is 1080x1920 at 30 fps. Layout uses the platform safe-area
  profile instead of component-local pixel constants.
- A screenshot's visual emphasis is supplied by a persisted derived asset or
  effect metadata. Do not recreate boxes or callouts from raw screenshot
  coordinates at render time.

## Git Checkpoints Are Required

- After completing each coherent, independently reversible unit of work,
  inspect its diff and create a Git commit before starting the next unit.
- Do not leave completed implementation work uncommitted across later tasks or
  turns. Keep commit messages scoped to the behavior or architecture changed.
- Never commit API keys, local provider configuration, case runs, rendered
  videos, caches, or unrelated user changes. Confirm the staged file list
  before every commit.
