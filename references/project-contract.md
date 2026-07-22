# Project contract

## `SCRIPT.md`

Narration is the exact text between:

```md
<!-- VO_START -->
...
<!-- VO_END -->
```

No text outside the markers is spoken.

## `project.json`

```json
{
  "title": "Product name",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "mode": "autonomous",
  "tts": {"speed": 1.0, "emotion": "happy"},
  "recipes": {"feature_demo": "recipes/feature-demo.json"},
  "result_assets": ["assets/result-01.png"]
}
```

Paths are resolved relative to the project directory.

## `storyboard.json`

```json
{
  "arc": "demo_loop",
  "video_direction": {
    "reveal_model": "voice-paced",
    "held_beats": ["beat_04"],
    "negative": ["front-loaded slideshow", "independent floating motion"]
  },
  "beats": [
    {
      "beat_id": "beat_01",
      "role": "feature_showcase",
      "voiceover": "输入一句需求，再点击生成。",
      "scene_kind": "website_operation",
      "recipe_id": "feature_demo",
      "asset_paths": [],
      "blueprint": "prompt-submit-result",
      "transition_in": "cut",
      "motion": "screen_push",
      "visual_windows": [
        {"cue": "输入一句需求", "label": "输入需求", "layout": "top-left", "motion": "cursor_fill"},
        {"cue": "点击生成", "label": "开始生成", "layout": "top-left", "motion": "click_pulse"}
      ]
    }
  ]
}
```

The concatenation of all beat `voiceover` values must equal `SCRIPT.md` after whitespace and punctuation normalization.

`visual_windows` prefer an exact spoken `cue`. The compiler aligns that cue to MiniMax tokens. `start_ratio` and `end_ratio` are only for holds or non-verbal intervals.
