from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_test.planner import ScenePlanner
from agent_test.project import (
    ProjectFiles,
    build_capture_inventory,
    create_project,
    load_project,
    read_json,
    validate_project,
    write_json,
)
from agent_test.storyboard import align_storyboard, load_storyboard, validate_storyboard
from agent_test.subtitles import build_subtitle_cues
from agent_test.tts import load_config, probe_duration_ms, synthesize

REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str, base_root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base_root / path).resolve()


def copy_asset(source: Path, public_root: Path, run_public: Path, filename: str) -> str:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = run_public / f"{filename}{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(public_root).as_posix()


def _runtime(source: Path) -> tuple[dict[str, Any], ProjectFiles | None, str, Path, Path, Path]:
    config, files, script = load_project(source)
    base_root = files.root if files else REPO_ROOT
    work_dir = files.work if files else REPO_ROOT / "runs" / source.stem
    render_dir = files.renders if files else work_dir / "final"
    work_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)
    return config, files, script, base_root, work_dir, render_dir


def prepare_voice(config: dict[str, Any], script: str, work_dir: Path, base_root: Path) -> tuple[Path, list[dict[str, Any]], int]:
    existing = config.get("existing_voice")
    if isinstance(existing, dict):
        audio = resolve_path(str(existing.get("audio") or ""), base_root)
        timing = resolve_path(str(existing.get("timing") or existing.get("tokens") or ""), base_root)
        if not audio.is_file() or not timing.is_file():
            raise ValueError("existing_voice requires valid audio and timing/tokens paths")
        payload = read_json(timing)
        raw_tokens = payload.get("tokens")
        if not isinstance(raw_tokens, list):
            raise ValueError("existing timing file must contain a tokens list")
        target = work_dir / "voice" / audio.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio, target)
        return target, [item for item in raw_tokens if isinstance(item, dict)], probe_duration_ms(target)

    tts_config = load_config(REPO_ROOT, config.get("tts") if isinstance(config.get("tts"), dict) else None)
    return synthesize(script, tts_config, work_dir / "voice")


def materialize_recipes(config: dict[str, Any], work_dir: Path, base_root: Path) -> dict[str, Path]:
    recipes = config.get("recipes") or {}
    if not isinstance(recipes, dict):
        raise ValueError("project.recipes must be an object")
    paths: dict[str, Path] = {}
    for recipe_id, value in recipes.items():
        if isinstance(value, str):
            path = resolve_path(value, base_root)
        elif isinstance(value, dict):
            path = work_dir / "recipes" / f"{recipe_id}.json"
            write_json(path, value)
        else:
            raise ValueError(f"invalid recipe: {recipe_id}")
        if not path.is_file():
            raise FileNotFoundError(path)
        paths[str(recipe_id)] = path
    return paths


def record_required_recipes(scenes: list[dict[str, Any]], recipe_paths: dict[str, Path], work_dir: Path) -> dict[str, Path]:
    required = sorted(
        {str(scene.get("recipe_id")) for scene in scenes if scene.get("kind") == "website_operation" and scene.get("recipe_id")}
    )
    recordings: dict[str, Path] = {}
    for recipe_id in required:
        recipe_path = recipe_paths.get(recipe_id)
        if recipe_path is None:
            raise ValueError(f"scene references missing recipe: {recipe_id}")
        output_dir = work_dir / "recordings" / recipe_id
        command = [
            "node",
            str(REPO_ROOT / "cdp-capture" / "bin" / "agent-record.js"),
            "--recipe",
            str(recipe_path),
            "--output",
            str(output_dir),
        ]
        subprocess.run(command, cwd=REPO_ROOT / "cdp-capture", check=True)
        recording = output_dir / "recording.mp4"
        if not recording.is_file():
            raise RuntimeError(f"CDP recorder produced no MP4: {recipe_id}")
        recordings[recipe_id] = recording
    return recordings


def build_props(
    config: dict[str, Any],
    project_key: str,
    audio_path: Path,
    duration_ms: int,
    cues: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    recordings: dict[str, Path],
    work_dir: Path,
    base_root: Path,
) -> Path:
    fps = int(config.get("fps", 30))
    public_root = REPO_ROOT / "remotion" / "public"
    run_public = public_root / "agent-test" / project_key
    if run_public.exists():
        shutil.rmtree(run_public)
    run_public.mkdir(parents=True, exist_ok=True)

    voice_path = copy_asset(audio_path, public_root, run_public, "voice")
    recording_paths = {
        recipe_id: copy_asset(path, public_root, run_public, f"recording-{recipe_id}") for recipe_id, path in recordings.items()
    }
    image_paths: dict[str, str] = {}
    rendered_scenes: list[dict[str, Any]] = []
    for scene in scenes:
        sources: list[str] = []
        recipe_id = scene.get("recipe_id")
        if scene.get("kind") == "website_operation" and recipe_id in recording_paths:
            sources = [recording_paths[str(recipe_id)]]
        else:
            for raw_path in scene.get("asset_paths") or []:
                source = resolve_path(str(raw_path), base_root)
                key = str(source)
                if key not in image_paths:
                    image_paths[key] = copy_asset(source, public_root, run_public, f"image-{len(image_paths) + 1:03d}")
                sources.append(image_paths[key])
        rendered_scenes.append({**scene, "sources": sources})

    props = {
        "width": int(config.get("width", 1080)),
        "height": int(config.get("height", 1920)),
        "fps": fps,
        "frame_count": max(1, round(duration_ms / 1000 * fps)),
        "voice_path": voice_path,
        "title": str(config.get("title") or "Agent Video Test"),
        "scenes": rendered_scenes,
        "subtitles": cues,
    }
    props_path = work_dir / "remotion_props.json"
    write_json(props_path, props)
    return props_path


def render(props_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "npx",
        "remotion",
        "render",
        "src/index.ts",
        "AgentTest",
        str(output_path),
        f"--props={props_path}",
    ]
    subprocess.run(command, cwd=REPO_ROOT / "remotion", check=True)


def inventory(source: Path) -> dict[str, Any]:
    config, files, _script, base_root, work_dir, _render_dir = _runtime(source)
    payload = build_capture_inventory(config, base_root)
    target = files.capture_inventory if files else work_dir / "capture_inventory.json"
    write_json(target, payload)
    return {"capture_inventory": str(target), "recipe_count": len(payload["recipes"]), "asset_count": len(payload["assets"])}


def audio(source: Path) -> dict[str, Any]:
    config, _files, script, base_root, work_dir, _render_dir = _runtime(source)
    audio_path, tokens, duration_ms = prepare_voice(config, script, work_dir, base_root)
    timing_path = work_dir / "timing_lock.json"
    write_json(timing_path, {"duration_ms": duration_ms, "tokens": tokens})
    fps = int(config.get("fps", 30))
    cues = build_subtitle_cues(tokens, fps=fps)
    if not cues:
        raise RuntimeError("no subtitle cues produced")
    subtitles_path = work_dir / "subtitles.json"
    write_json(subtitles_path, {"fps": fps, "cues": cues})
    audio_meta = {
        "voice_path": str(audio_path),
        "duration_ms": duration_ms,
        "timing_lock": str(timing_path),
        "subtitles": str(subtitles_path),
    }
    write_json(work_dir / "audio_meta.json", audio_meta)
    return audio_meta


def plan(source: Path) -> dict[str, Any]:
    config, files, script, _base_root, work_dir, _render_dir = _runtime(source)
    timing_path = work_dir / "timing_lock.json"
    subtitles_path = work_dir / "subtitles.json"
    if not timing_path.is_file() or not subtitles_path.is_file():
        audio(source)
    tokens = read_json(timing_path).get("tokens")
    if not isinstance(tokens, list):
        raise ValueError("timing_lock.json has no tokens")
    cues = read_json(subtitles_path).get("cues")
    if not isinstance(cues, list):
        raise ValueError("subtitles.json has no cues")

    recipes = config.get("recipes") or {}
    result_assets = [str(value) for value in config.get("result_assets") or []]
    fps = int(config.get("fps", 30))
    storyboard: dict[str, Any] = {}
    if files and files.storyboard_json.is_file():
        storyboard = load_storyboard(files.storyboard_json)
        errors = validate_storyboard(storyboard, script=script, recipes=recipes, result_assets=result_assets)
        if errors:
            raise ValueError("invalid storyboard:\n- " + "\n- ".join(errors))
        scenes = align_storyboard(storyboard, tokens, fps=fps)
        source_kind = "storyboard"
    else:
        scenes = ScenePlanner().plan(cues, recipes=recipes, result_assets=result_assets)
        source_kind = "planner_fallback"

    visual_plan = {
        "source": source_kind,
        "video_direction": storyboard.get("video_direction", {}) if source_kind == "storyboard" else {},
        "scenes": scenes,
    }
    target = work_dir / "visual_plan.json"
    write_json(target, visual_plan)
    return {"visual_plan": str(target), "scene_count": len(scenes), "source": source_kind}


def build(source: Path, *, should_render: bool = True) -> dict[str, Any]:
    config, files, _script, base_root, work_dir, render_dir = _runtime(source)
    visual_plan_path = work_dir / "visual_plan.json"
    if not visual_plan_path.is_file():
        plan(source)
    scenes = read_json(visual_plan_path).get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("visual_plan.json has no scenes")
    audio_meta = read_json(work_dir / "audio_meta.json")
    audio_path = Path(str(audio_meta["voice_path"]))
    duration_ms = int(audio_meta["duration_ms"])
    cues = read_json(work_dir / "subtitles.json").get("cues")
    if not isinstance(cues, list):
        raise ValueError("subtitles.json has no cues")

    recipe_paths = materialize_recipes(config, work_dir, base_root)
    recordings = record_required_recipes(scenes, recipe_paths, work_dir)
    project_key = files.root.name if files else source.stem
    props_path = build_props(config, project_key, audio_path, duration_ms, cues, scenes, recordings, work_dir, base_root)
    output_path = render_dir / "video.mp4"
    if should_render:
        render(props_path, output_path)
    report = {
        "project": str(files.root if files else source),
        "duration_ms": duration_ms,
        "scene_count": len(scenes),
        "recordings": {key: str(value) for key, value in recordings.items()},
        "remotion_props": str(props_path),
        "final_video": str(output_path) if should_render else None,
    }
    write_json(work_dir / "report.json", report)
    return report


def check(source: Path) -> dict[str, Any]:
    config, files, script, _base_root, work_dir, render_dir = _runtime(source)
    errors: list[str] = []
    if files:
        errors.extend(validate_project(files))
        if files.storyboard_json.is_file():
            storyboard = load_storyboard(files.storyboard_json)
            errors.extend(
                validate_storyboard(
                    storyboard,
                    script=script,
                    recipes=config.get("recipes") or {},
                    result_assets=[str(value) for value in config.get("result_assets") or []],
                )
            )
    for name in ("timing_lock.json", "subtitles.json", "visual_plan.json", "remotion_props.json"):
        if not (work_dir / name).is_file():
            errors.append(f"missing work artifact: {name}")
    final_video = render_dir / "video.mp4"
    return {"ok": not errors, "errors": errors, "final_video": str(final_video) if final_video.is_file() else None}


def run(source: Path, *, should_render: bool = True) -> dict[str, Any]:
    inventory(source)
    audio(source)
    plan(source)
    report = build(source, should_render=should_render)
    validation = check(source)
    if validation["errors"] and should_render:
        raise RuntimeError("project check failed:\n- " + "\n- ".join(validation["errors"]))
    report["check"] = validation
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skill-oriented product demo video pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    init_parser = sub.add_parser("init")
    init_parser.add_argument("project", type=Path)
    init_parser.add_argument("--title", required=True)
    init_parser.add_argument("--script", default="")
    for name in ("inventory", "audio", "plan", "check"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
    for name in ("build", "run"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
        command.add_argument("--no-render", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    known = {"init", "inventory", "audio", "plan", "build", "check", "run"}
    if argv and argv[0] not in known and not argv[0].startswith("-"):
        argv.insert(0, "run")
    args = _parser().parse_args(argv)
    if args.command == "init":
        files = create_project(args.project, title=args.title, script=args.script)
        result: dict[str, Any] = {"project": str(files.root)}
    elif args.command == "inventory":
        result = inventory(args.project)
    elif args.command == "audio":
        result = audio(args.project)
    elif args.command == "plan":
        result = plan(args.project)
    elif args.command == "build":
        result = build(args.project, should_render=not args.no_render)
    elif args.command == "check":
        result = check(args.project)
    else:
        result = run(args.project, should_render=not args.no_render)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
