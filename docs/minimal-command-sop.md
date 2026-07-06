# Minimal Command SOP

Use this SOP to keep execution predictable. Do not recursively inspect the whole workspace unless a required path is missing.

## Command Budget

For a normal run, start with no more than these checks:

1. Python availability.
2. ffmpeg and ffprobe availability.
3. HyperFrames availability.
4. Case path and material path existence.
5. One ASR/TTS smoke check only when voice generation is required in this turn.

## Step 1: Resolve Paths

Prefer explicit user paths. If a path is missing, stop and report it.

Expected variables:

```text
SKILL_ROOT=<path to video-agent skill>
CASE_DIR=<path to user case>
MATERIALS_DIR=<optional path to user materials>
FRONTEND_DIR=<optional path to frontend project>
```

When scripts exist, they should also support:

```powershell
$env:VIDEO_AGENT_SKILL_ROOT="C:\Users\CNGG\Documents\video_generate\video-agent"
```

Skill root smoke check:

```powershell
python "<SKILL_ROOT>\scripts\utils\skill_path.py"
```

## Step 2: Minimal Dependency Check

Windows PowerShell:

```powershell
python --version
ffmpeg -version
ffprobe -version
npx hyperframes --version
```

FunASR smoke check:

```powershell
python -c "from funasr import AutoModel; print('funasr_import_ok')"
```

Voice clone endpoint smoke check should be non-destructive. Prefer a short request only when the user has authorized voice generation for the case.

## Step 3: Case Scaffold

Create `<CASE_DIR>` inside the current `video-agent` project. Do not create cases beside this repository or in unrelated `Documents` folders. If a user supplies `<MATERIALS_DIR>` outside the project, treat it only as an import source; the registration step must copy/freeze usable media into `<CASE_DIR>\assets\static`.

Use:

```powershell
python scripts\init_case.py `
  --case "<CASE_DIR>" `
  --materials "<MATERIALS_DIR>" `
  --voice-policy default `
  --ending-policy default `
  --json
```

Expected result:

```json
{
  "ok": true,
  "code": "ok",
  "reason": "",
  "data": {
    "case_dir": "<CASE_DIR>",
    "voice_prompt": "audio/voice_prompt_5s.wav",
    "ending_policy": "default"
  }
}
```

If this command fails before creating the case, report the structured error. Create the case structure manually only when the script itself is unavailable:

```text
case/
  input.json
  assets/
    browser/
      raw/
      annotated/
    results/
  audio/
  hyperframes/
  output/
    versions/
    qa/
    reports/
```

## Step 4: Material Registration

Website case:

- for stable 柯幻熊猫 pages, seed known structure from the site profile before live capture:

```powershell
python scripts\apply_site_profile.py `
  --case "<CASE_DIR>" `
  --profile kehuanxiongmao `
  --feature signboard `
  --frontend-root "C:\Users\CNGG\Documents\video_generate\wanxiang-frontend" `
  --json
```

- use Kimi WebBridge to capture evidence
- prefer `scripts/kimi_webbridge.py` for WebBridge calls to avoid Windows/PowerShell JSON quoting issues:

```powershell
python scripts\kimi_webbridge.py `
  --session "kehuanxiongmao-demo" `
  --action navigate `
  --args "{""url"":""https://kehuanxiongmao.com"",""newTab"":true,""group_title"":""柯幻熊猫素材采集""}" `
  --json
```

- save screenshots and page text under the case
- write or update `browser_materials.json`
- for 柯幻熊猫, follow `rules/kehuanxiongmao-capture.md` and write `image_resources.json` plus `generation_receipts.json`

Static material case:

- register local files into `asset_manifest.json`
- inspect images with the available vision model
- write `material_understanding.json`

Command:

```powershell
python scripts\register_materials.py `
  --case "<CASE_DIR>" `
  --materials "<MATERIALS_DIR>" `
  --json
```

Do not assign assets to script segments using filenames alone.

After browser or static image assets exist, refresh the image resource catalog:

```powershell
python scripts\build_image_resources.py `
  --case "<CASE_DIR>" `
  --default-feature "logo" `
  --json
```

Manual site-profile refresh:

```powershell
python scripts\apply_site_profile.py `
  --case "<CASE_DIR>" `
  --profile kehuanxiongmao `
  --feature signboard `
  --frontend-root "C:\Users\CNGG\Documents\video_generate\wanxiang-frontend" `
  --refresh-needed `
  --force `
  --json
```

Use `--refresh-needed` when live WebBridge evidence no longer matches the profile. Then update `references/site_profiles/kehuanxiongmao.json` from frontend code plus fresh WebBridge snapshots before using it as ready again.

## Step 4.5: Contract Validation

After scaffold or after any manual edit to `input.json` / `video_project.json`, run:

```powershell
python scripts\validate_video_project.py --case "<CASE_DIR>" --json
```

Before rendering, run strict validation:

```powershell
python scripts\validate_video_project.py --case "<CASE_DIR>" --strict --json
```

Strict validation is expected to fail while `video_project.json` is still a placeholder.
Strict validation also fails before real voice audio and ASR subtitle segments exist.

## Step 4.6: Planner Context And Acceptance

Prepare model-ready context after assets are registered:

```powershell
python scripts\prepare_planner_context.py `
  --case "<CASE_DIR>" `
  --stage all `
  --json
```

Expected outputs:

```text
output/planner/all_planner_context.json
output/planner/all_planner_brief.md
```

Use the embedded prompt contracts to ask the available vision/text model for JSON only. Accept model output through the validator, not by copying directly into case files:

```powershell
python scripts\accept_planner_output.py `
  --case "<CASE_DIR>" `
  --kind material `
  --input "<MODEL_MATERIAL_JSON>" `
  --json

python scripts\accept_planner_output.py `
  --case "<CASE_DIR>" `
  --kind script `
  --input "<MODEL_SCRIPT_JSON>" `
  --json
```

The accept step checks required fields, asset IDs, duplicate segment IDs, speech density, and fixed-outro exclusion assumptions. Use `--force` only when intentionally replacing a reviewed artifact.

## Step 5: Planning Artifacts

Generate these in order:

```text
material_understanding.json
image_resources.json
video_script.json
voice_plan.json
video_project.json
```

Rules:

- `video_script.json` contains semantic segments.
- `voice_plan.json` contains final spoken text and high-risk terms.
- `video_project.json` is the source of truth for rendering.
- The fixed outro is represented in `ending_track`, not in script segments.

## Step 6: Voice And ASR

Use the case-local prompt audio:

```text
audio/voice_prompt_5s.wav
```

Do not call the voice clone API with the bundled skill asset directly.

Create voice plan from reviewed script:

```powershell
python scripts\create_voice_plan.py `
  --case "<CASE_DIR>" `
  --json
```

Generate voice:

```powershell
python scripts\generate_voice.py `
  --case "<CASE_DIR>" `
  --json
```

After voice generation:

```powershell
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 audio\voice.wav
```

Then run FunASR:

```powershell
python scripts\run_funasr.py `
  --case "<CASE_DIR>" `
  --json
```

Expected ASR outputs:

```text
output/funasr/voice_raw.json
output/funasr/funasr_alignment.json
```

Run voice QA:

```powershell
python scripts\check_voice_qa.py `
  --case "<CASE_DIR>" `
  --text "<REVIEWED_VOICE_TEXT>" `
  --json
```

If ASR fails high-risk terms, repair voice before render.

Apply ASR timing to reviewed script segments:

```powershell
python scripts\apply_asr_alignment.py `
  --case "<CASE_DIR>" `
  --update-project `
  --json
```

Build render-ready project:

```powershell
python scripts\build_video_project.py `
  --case "<CASE_DIR>" `
  --json
```

## Step 7: Render

Once render scripts exist, use:

```powershell
python scripts\build_hyperframes.py --case "<CASE_DIR>" --json
python scripts\render_hyperframes.py --case "<CASE_DIR>" --json
```

Expected behavior:

- HyperFrames renders the main video.
- ffmpeg appends default outro when `ending_track.policy` is `default`.
- output files are versioned.
- no accepted output is overwritten.

## Step 8: QA

Build contact sheet:

```powershell
python scripts\make_contact_sheet.py `
  --case "<CASE_DIR>" `
  --json
```

Run:

```powershell
python scripts\render_qa.py --case "<CASE_DIR>" --json
```

Required outputs:

```text
output/qa/<label>_contact_sheet.jpg
output/reports/<label>_render_report.json
```

A passing report must include:

- voice checks
- subtitle checks
- visual/layout checks
- browser/material checks
- render/package checks

Run hygiene before final delivery:

```powershell
python scripts\check_case_hygiene.py --case "<CASE_DIR>" --json
```

## Retry Rules

Patch based on concrete error output only.

For a first implementation, use this retry budget:

- dependency failure: stop and report
- missing path: stop and report
- script bug: patch and rerun once
- voice QA failure: repair voice/text and rerun ASR once
- render failure: patch render input or composition and rerun once
- layout QA failure: regenerate affected scene and QA frames once

If the same class of failure repeats after the retry budget, report the blocker and the next required human decision.

## Anti-Patterns

- Do not scan entire user drives looking for assets.
- Do not overwrite accepted output versions.
- Do not mutate bundled skill assets.
- Do not continue from estimated subtitle timing after voice exists.
- Do not treat the fixed outro as part of script generation.
- Do not add undeclared overlay text to compensate for unclear visuals.
- Do not call a preview final when QA has known failures.
