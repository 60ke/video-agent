# Material-Driven Video Refactor Plan

This is the current implementation direction for `video-agent`.

## Goal

Use a material library as the center of the video pipeline:

```text
site screenshots / result images
-> structured asset registration
-> GPT image prepared 9:16 keyframes
-> visual-first script
-> Minimax voice + word timing
-> multi-track video_project.json
-> FFmpeg render with controlled whole-frame motion and overlay_track
```

The standard video path no longer uses browser video capture. CDP is a screenshot and coordinate-evidence tool only.

## Material Types

- `网站主页截图`: one logged-in homepage/dashboard screenshot per site.
- `功能入口截图`: opened menu/dropdown/route-entry state with the target function visible.
- `参数面板截图`: feature page or form panel showing required inputs and the generate button.
- `结果图_*`: saved generated result images, crops, or exports.
- `AI优化关键帧`: GPT image prepared 1080x1920 keyframes derived from the screenshots or result images.

## Naming

Use Chinese filenames to avoid losing website label information:

```text
柯幻熊猫_文生图_文化墙_功能入口截图.png
柯幻熊猫_文生图_文化墙_参数面板截图.png
柯幻熊猫_文生图_图文广告_车贴_参数面板截图.png
```

For `图文广告`, keep the extra child level: `文生图 -> 图文广告 -> 子功能`.

## Registration

`scripts/register_site_assets.py` parses `assets/sites` filenames and writes:

- `asset_manifest.json`
- `image_resources.json`

`scripts/register_result_assets.py` parses `assets/results` filenames and writes the same case files for result images:

```text
柯幻熊猫_文生图_文化墙_企业展厅_结果图_01.png
柯幻熊猫_文生图_图文广告_车贴_汽车服务_结果图_01.png
```

Result registration preserves feature path, industry/scene label, result sequence, origin (`result_asset_library` or `live_generated_result`), and receipt id when available.

Registration should preserve:

- feature path and feature id
- screenshot type
- workflow step
- source asset id
- callout metadata
- visible text and prompt inputs when known

## Callouts

CDP should not bake red boxes, arrows, cursor circles, or click pulses into clean screenshots. It should output target boxes and semantic hints as metadata. Later stages decide how to display them:

- GPT image: static composition/layout optimization.
- `overlay_track`: dynamic red boxes, click rings, arrow callouts, label tags.

This keeps callouts aligned after 9:16 conversion and lets video timing match subtitles.

## GPT Image Keyframes

`scripts/prepare_gpt_image_keyframes.py` should recognize the site screenshot library and create prepared assets:

- homepage keyframe: fill width, highlight the `文生图` entry.
- feature-entry keyframe: preserve UI, mark the exact hover/dropdown child item.
- parameter-panel keyframe: preserve the original UI and avoid arbitrary crop.
- result keyframe: preserve generated content and optimize only ratio/composition.

Prepared assets are registered with:

```json
{
  "origin": "gpt_image_site_keyframe",
  "source_asset_id": "<original screenshot asset id>",
  "workflow_step": "prepared_site_keyframe",
  "quality": {"ai_verified": true}
}
```

## Planning

Planner context must expose a structured material pool grouped by site, feature path, screenshot type, workflow step, and prepared status. For a single-feature video:

1. Prefer same-feature prepared keyframes.
2. Fall back to same-feature raw screenshots only when no prepared keyframe exists.
3. Never cross-pick screenshots from another feature just because the UI looks similar.
4. Use real result assets for result claims.
5. Use multiple result images when the copy claims multiple scenes, styles, or industries.

## Rendering

`video_project.json` is multi-track:

- `visual_track`: image, site flow steps, result gallery, or image sequence.
- `subtitle_track`: Minimax word timing mapped to reviewed script segments.
- `overlay_track`: dynamic callouts from asset metadata.
- `audio_tracks`: voice, BGM, SFX.
- `ending_track`: appended outro, not part of script planning.

Motion is controlled:

- dense UI and multi-image layouts use `hold`.
- simple result images may use small `push_in` or `pull_out`.
- no arbitrary local crop, pan, or zoom repair.
- identical consecutive visual events merge into one continuous shot.

## Current Priority

1. Keep screenshot registration and prepared keyframe generation stable.
2. Keep Planner selection constrained to same-feature materials.
3. Validate subtitle timing, visual duration, overlay timing, and result-image authenticity before treating a render as final.
