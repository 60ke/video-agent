---
name: setup
description: Skill root resolution and case-script bootstrap rules.
---

# Setup Rules

Use `scripts/utils/skill_path.py` whenever a case script needs bundled skill assets or references.

## Environment Variable

Prefer explicit configuration in mixed-agent environments:

```powershell
$env:VIDEO_AGENT_SKILL_ROOT="C:\Users\CNGG\Documents\video_generate\video-agent"
```

## Python Bootstrap

From scripts inside the skill package:

```python
from scripts.utils.skill_path import require_skill_root, require_default_assets

skill_root = require_skill_root(__file__)
assets = require_default_assets(skill_root)
```

From case-local scripts, either set `VIDEO_AGENT_SKILL_ROOT` or add the skill root to `sys.path` before importing.

## Asset Rule

Do not mutate bundled assets.

- Copy `assets/voice/default_voice_clone_prompt_5s.wav` into the case audio directory before voice clone.
- Append `assets/outro/default_panda_outro.mp4` during postprocess; do not edit it in place.

## Failure Rule

If the helper cannot resolve the skill root, stop and report all attempted paths from the exception. Do not search the whole drive.
