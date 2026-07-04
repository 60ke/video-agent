# Video Agent Skill Development Plan

## Goal

Build a reusable agent skill that turns a target website into a vertical feature seeding/product demo video.

P0 stack:

```text
Kimi WebBridge -> browser capture
Vision model -> material/layout understanding
TTS -> voice
FunASR -> subtitle timing and voice QA
video_project.json -> multi-track contract
HyperFrames -> render
ffmpeg -> postprocess and QA support
```

## Guiding Principles

- Build one stable path before adding alternatives.
- Use Kimi WebBridge as the P0 browser execution layer.
- Use HyperFrames as the P0 renderer.
- Use `video_project.json` as the source of truth.
- Keep HyperFrames creatively flexible, but enforce timing, asset, caption, and QA constraints.
- QA must be executable and must block final delivery when it fails.
- Retain brand/copywriting knowledge as references, not as competing implementation specs.
- Keep business scripts inside each user case folder, not inside the skill package.
- Every reusable CLI should support machine-readable output:

```json
{
  "ok": true,
  "code": "ok",
  "reason": "",
  "data": {}
}
```

## Patterns Borrowed From jianying-editor-skill

The `jianying-editor-skill` package is useful as a model for a dependency-orchestrating skill. Borrow these patterns:

1. `SKILL.md` as a router, not a full manual.
   - Keep trigger rules, required reads, workflow order, and non-negotiable constraints there.
   - Put long domain rules into `rules/` or `references/`.

2. Add an agent playbook.
   - One default execution path.
   - A routing matrix for common tasks.
   - Mandatory acceptance checklist before final response.

3. Add a minimal command SOP.
   - Limit environment probing.
   - Generate one runnable case script or run one pipeline command.
   - Patch from concrete errors instead of endlessly exploring.

4. Add skill-root resolution helpers.
   - Support `VIDEO_AGENT_SKILL_ROOT`.
   - Probe common agent layouts such as `.codex/skills`, `.agent/skills`, `.claude/skills`, `.trae/skills`, and local `skills/`.
   - Return attempted paths in errors so another agent can fix setup quickly.

5. Add rule files by task.
   - `rules/setup.md`
   - `rules/browser-webbridge.md`
   - `rules/project-contract.md`
   - `rules/voice-asr.md`
   - `rules/hyperframes-render.md`
   - `rules/visual-layout.md`
   - `rules/qa.md`

6. Add repo and output hygiene checks.
   - Do not track runtime caches, temporary captures, rendered videos, or generated voice files inside the skill repo.
   - Generated artifacts belong under the user case directory.

## Phase 0: Skill Package Shape

Objective: make the current folder usable as a proper skill project.

Tasks:

1. Keep `SKILL.md` lean.
   - Move long implementation detail into `references/`.
   - Keep only trigger, required reads, workflow, and non-negotiable rules in `SKILL.md`.

2. Create recommended skill directories.

```text
video-agent/
  SKILL.md
  references/
    SPEC.md
    DEPENDENCIES.md
    SCHEMA.md
    QA.md
    copywriting-rules.md
    copywriting-options.md
  rules/
    setup.md
    browser-webbridge.md
    project-contract.md
    voice-asr.md
    hyperframes-render.md
    visual-layout.md
    qa.md
  docs/
    agent-playbook.md
    minimal-command-sop.md
  scripts/
    utils/
  assets/
    voice/
      default_voice_clone_prompt_5s.wav
      default_voice_clone_prompt.metadata.json
    outro/
      default_panda_outro.mp4
      default_panda_outro.metadata.json
  examples/
```

3. Move current canonical docs into `references/`.

4. Add `docs/agent-playbook.md`.
   - default end-to-end execution path
   - task routing matrix
   - mandatory acceptance checklist

5. Add `docs/minimal-command-sop.md`.
   - dependency check command budget
   - case scaffold command
   - validate/render/QA command order
   - retry policy based on concrete failures

6. Add `scripts/utils/skill_path.py`.
   - resolves the installed skill root
   - exposes reusable script import bootstrap
   - supports `VIDEO_AGENT_SKILL_ROOT`

7. Add `agents/openai.yaml` only when installing as a Codex skill.

Deliverables:

- valid skill folder structure
- no obsolete draft specs
- `SKILL.md` under 500 lines
- root-resolution helper for user-project scripts
- agent playbook and minimal command SOP

Acceptance:

- another agent can read `SKILL.md` and know which reference file to open for each task
- no doc says MoviePy/Remotion/Playwright is P0
- generated case files are clearly separated from skill package files

## Phase 1: Minimal Executable Pipeline

Objective: generate one complete video from a website using controlled, partly manual inputs.

Tasks:

1. Implement case scaffold.

```text
scripts/init_case.py
```

Creates:

```text
case/
  input.json
  website_knowledge.json
  feature_cards.json
  operation_recipes.json
  browser_materials.json
  video_script.json
  video_project.json
  assets/
  audio/
    voice_prompt_5s.wav
  hyperframes/
  output/
```

Default behavior:

- If `input.json.voice_config.prompt_audio_policy` is absent or `default`, copy `assets/voice/default_voice_clone_prompt_5s.wav` from the skill into `case/audio/voice_prompt_5s.wav`.
- If `prompt_audio_policy` is `custom`, convert and validate the user prompt into `case/audio/voice_prompt_5s.wav`.
- If `prompt_audio_policy` is `none`, skip voice clone and use plain TTS.
- If `input.json.ending_track.policy` is absent or `default`, set `ending_track` to the bundled fixed panda outro.
- The fixed outro is appended after main render; it must not affect script, voice, subtitle, or visual timing.

Every script should accept a `--json` flag when practical and return:

```json
{
  "ok": false,
  "code": "voice_asr_mismatch",
  "reason": "FunASR did not recognize the brand term.",
  "data": {}
}
```

2. Implement schema validation.

```text
scripts/validate_video_project.py
```

Checks:

- required top-level keys
- asset paths exist
- track timing is non-overlapping where required
- voice/subtitle/visual references resolve
- QA rules exist

3. Implement manual WebBridge material import.

P0 can start with agent-driven WebBridge capture and a script that registers captured files into `browser_materials.json`.

```text
scripts/register_browser_materials.py
```

4. Implement voice and ASR helpers.

```text
scripts/generate_voice.py
scripts/run_funasr.py
scripts/apply_asr_alignment.py
scripts/check_voice_qa.py
```

5. Implement HyperFrames composition generator.

```text
scripts/build_hyperframes.py
```

Inputs:

- `video_project.json`
- frozen assets
- voice audio

Outputs:

- `hyperframes/index.html`
- `hyperframes/media/*`

6. Implement render wrapper.

```text
scripts/render_hyperframes.py
```

Runs:

- `npx hyperframes lint`
- `npx hyperframes validate`
- `npx hyperframes render`
- ffmpeg outro concat when `ending_track.policy` is `default` or `custom`

7. Implement QA frame extraction.

```text
scripts/make_contact_sheet.py
scripts/render_qa.py
```

8. Implement repo/output hygiene checks.

```text
scripts/check_case_hygiene.py
```

Checks:

- generated media stays under the case directory
- skill package has no runtime caches
- no accepted output version is overwritten
- temporary debug captures are either registered or cleaned

Deliverables:

- one successful end-to-end case
- `output/versions/<label>.mp4`
- `output/qa/<label>_contact_sheet.jpg`
- `output/reports/<label>_render_report.json`

Acceptance:

- final video is playable
- voice is not clipped
- subtitles align to ASR timing
- no black frames
- no tiny/unreadable UI shots
- no meaningless empty dual panels
- same-asset scenes do not flicker

## Phase 2: WebBridge Automation

Objective: reduce manual capture and make website exploration repeatable.

Tasks:

1. Define WebBridge command protocol used by the agent.
   - navigation
   - screenshot
   - read visible text
   - click/fill/select/upload
   - result wait

2. Implement operation recipe executor wrapper.

```text
scripts/execute_operation_recipe.py
```

If WebBridge only exposes agent-facing actions and not a direct CLI/API, document the manual-agent execution pattern and keep the recipe as an instruction artifact.

3. Save browser evidence.

Required artifacts:

- screenshots
- page text
- DOM summary if available
- action events
- result-ready evidence
- error screenshots

4. Add privacy/safety checks.

Block:

- payment
- deletion
- publishing
- external messaging
- account changes
- leaking credentials or private data

Deliverables:

- `website_knowledge.json`
- `feature_cards.json`
- `operation_recipes.json`
- `browser_materials.json`

Acceptance:

- selected feature has URL/page evidence
- recipe has safe actions only
- captured materials support all demo/result claims

## Phase 3: Planning Agent Quality

Objective: make script, visuals, and layout decisions robust.

Tasks:

1. Build planner prompt set.

```text
references/prompts/
  website_research.md
  feature_analysis.md
  operation_recipe.md
  script_director.md
  material_curator.md
  timeline_director.md
  render_qa.md
```

2. Integrate copywriting references.
   - Use `references/copywriting-rules.md` as the brand/copywriting rule source.
   - Use `references/copywriting-options.md` as the option matrix source.
   - Ensure final output is structured segments, not plain copy.

3. Add visual reasoning fields.

Every visual event should include:

- page/material role
- display mode
- focus region
- readability expectation
- subject size expectation
- subtitle-safe expectation
- layout reason

4. Add layout repair loop.

When QA fails:

- mark event `needs_layout_revision`
- propose repair action
- rebuild only affected scene when possible

Deliverables:

- robust planner prompts
- example `video_project.json`
- example repair report

Acceptance:

- agent can explain why each visual matches each subtitle
- agent can identify and fix unreasonable layouts before final delivery

## Phase 4: Voice Quality Automation

Objective: prevent choppy brand slogans and timing mismatch.

Tasks:

1. Add high-risk term detection.

High-risk terms:

- brand names
- product names
- mixed Chinese/English terms
- final slogans
- uncommon proper nouns

2. Generate multiple candidates for high-risk segments.

3. Run ASR comparison.

Reject if:

- brand/product term is misrecognized
- segment is too fast or too slow
- slogan has internal pauses above policy

4. Support segment-level audio replacement.

Use ffmpeg crossfade or concat after regenerating a failed segment.

Deliverables:

- `voice_qa_report.json`
- repaired voice path when needed

Acceptance:

- final slogans do not sound one-word-at-a-time
- brand terms are recognized correctly
- voice duration matches the main video timeline

## Phase 5: Packaging As A Codex Skill

Objective: install and validate the skill for new agent conversations.

Tasks:

1. Move final skill to Codex skills path when ready.

Suggested path:

```text
C:/Users/CNGG/.codex/skills/video-agent
```

2. Validate skill structure.

Use `skill-creator` guidance:

- required `SKILL.md`
- concise frontmatter
- references loaded progressively
- scripts reusable and tested

3. Add examples.

```text
examples/
  input.example.json
  video_project.example.json
  render_report.example.json
```

4. Run forward tests.

Test prompts:

- generate a video from a simple public website
- generate a video from a logged-in local browser state
- generate a video from a static material folder

Deliverables:

- installable skill folder
- passing validation
- at least one successful forward test

Acceptance:

- a new agent can use the skill without reading this conversation
- missing dependencies are reported clearly
- output includes final video and QA report

## Implementation Order

Recommended immediate next tasks:

1. Restructure docs into `references/`.
2. Add `examples/input.example.json`.
3. Add `examples/video_project.example.json`.
4. Implement `scripts/validate_video_project.py`.
5. Implement `scripts/init_case.py`.
6. Implement HyperFrames generator skeleton.
7. Run one static-material smoke case before full WebBridge automation.

## Key Risks

1. WebBridge API/automation surface may be more agent-facing than script-facing.
   - Mitigation: keep operation recipes as agent instructions first; automate only stable capabilities.

2. Voice engines may not expose speed/prosody controls.
   - Mitigation: measure, ASR-check, regenerate high-risk segments, use ffmpeg only within policy.

3. HyperFrames layout freedom can create visually invalid scenes.
   - Mitigation: encode layout QA into `video_project.json` and render reports.

4. Browser materials may contain private data.
   - Mitigation: add privacy QA before render and mask/recapture when needed.

5. Agent may skip QA under time pressure.
   - Mitigation: make QA report required output and refuse final status when failed.

## Definition Of Done For P0

P0 is done when:

- one target website can be researched through Kimi WebBridge
- feature, script, voice, subtitles, visuals, and layout are represented in `video_project.json`
- HyperFrames renders the main video
- ffmpeg produces the final packaged video
- contact sheet and render report are generated
- QA catches voice, subtitle, visual, and layout failures
- a fresh agent can follow `SKILL.md` and references to reproduce the process
