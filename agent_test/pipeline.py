from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from agent_test.planner import ScenePlanner
from agent_test.subtitles import build_subtitle_cues
from agent_test.tts import load_config, probe_duration_ms, read_json, synthesize, write_json

REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def copy_asset(source: Path, public_root: Path, run_public: Path, filename: str) -> str:
    if not source.is_file():
        raise FileNotFoundError(source)
    target = run_public / f"{filename}{source.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(public_root).as_posix()


def prepare_voice(project: dict[str, Any], run_dir: Path) -> tuple[Path, list[dict[str, Any]], int]:
    existing = project.get("existing_voice")
    if isinstance(existing, dict):
        audio = resolve_path(str(existing.get("audio") or ""))
        timing = resolve_path(str(existing.get("timing") or existing.get("tokens") or ""))
        if not audio.is_file() or not timing.is_file():
            raise ValueError("existing_voice requires valid audio and timing/tokens paths")
        payload = read_json(timing)
        raw_tokens = payload.get("tokens")
        if not isinstance(raw_tokens, list):
            raise ValueError("existing timing file must contain a tokens list")
        target = run_dir / "voice" / audio.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio, target)
        return target, [item for item in raw_tokens if isinstance(item, dict)], probe_duration_ms(target)

    config = load_config(REPO_ROOT, project.get("tts") if isinstance(project.get("tts"), dict) else None)
    return synthesize(str(project["script"]), config, run_dir / "voice")


def materialize_recipes(project: dict[str, Any], run_dir: Path) -> dict[str, Path]:
    recipes = project.get("recipes") or {}
    if not isinstance(recipes, dict):
        raise ValueError("project.recipes must be an object")
    paths: dict[str, Path] = {}
    for recipe_id, value in recipes.items():
        if isinstance(value, str):
            path = resolve_path(value)
        elif isinstance(value, dict):
            path = run_dir / "recipes" / f"{recipe_id}.json"
            write_json(path, value)
        else:
            raise ValueError(f"invalid recipe: {recipe_id}")
        if not path.is_file():
            raise FileNotFoundError(path)
        paths[str(recipe_id)] = path
    return paths


def record_required_recipes(scenes: list[dict[str, Any]], recipe_paths: dict[str, Path], run_dir: Path) -> dict[str, Path]:
    required = sorted({str(scene.get("recipe_id")) for scene in scenes if scene.get("kind") == "website_operation" and scene.get("recipe_id")})
    recordings: dict[str, Path] = {}
    for recipe_id in required:
        recipe_path = recipe_paths.get(recipe_id)
        if recipe_path is None:
            raise ValueError(f"scene references missing recipe: {recipe_id}")
        output_dir = run_dir / "recordings" / recipe_id
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
    project: dict[str, Any],
    run_id: str,
    audio_path: Path,
    duration_ms: int,
    cues: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    recordings: dict[str, Path],
    run_dir: Path,
) -> Path:
    fps = int(project.get("fps", 30))
    public_root = REPO_ROOT / "remotion" / "public"
    run_public = public_root / "agent-test" / run_id
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
                source = resolve_path(str(raw_path))
                key = str(source)
                if key not in image_paths:
                    image_paths[key] = copy_asset(source, public_root, run_public, f"image-{len(image_paths) + 1:03d}")
                sources.append(image_paths[key])
        rendered_scenes.append({**scene, "sources": sources})

    props = {
        "width": int(project.get("width", 1080)),
        "height": int(project.get("height", 1920)),
        "fps": fps,
        "frame_count": max(1, round(duration_ms / 1000 * fps)),
        "voice_path": voice_path,
        "title": str(project.get("title") or "Agent Video Test"),
        "scenes": rendered_scenes,
        "subtitles": cues,
    }
    props_path = run_dir / "remotion_props.json"
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


def run(project_path: Path, *, should_render: bool = True) -> dict[str, Any]:
    project = read_json(project_path.resolve())
    script = str(project.get("script") or "").strip()
    if not script:
        raise ValueError("project.script is required")

    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = REPO_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True)
    shutil.copy2(project_path, run_dir / "project.json")

    audio_path, tokens, duration_ms = prepare_voice(project, run_dir)
    write_json(run_dir / "timing_lock.json", {"duration_ms": duration_ms, "tokens": tokens})

    fps = int(project.get("fps", 30))
    cues = build_subtitle_cues(tokens, fps=fps)
    if not cues:
        raise RuntimeError("no subtitle cues produced")
    write_json(run_dir / "subtitles.json", {"fps": fps, "cues": cues})

    recipes = project.get("recipes") or {}
    result_assets = [str(value) for value in project.get("result_assets") or []]
    scenes = ScenePlanner().plan(cues, recipes=recipes, result_assets=result_assets)
    write_json(run_dir / "scene_plan.json", {"scenes": scenes})

    recipe_paths = materialize_recipes(project, run_dir)
    recordings = record_required_recipes(scenes, recipe_paths, run_dir)
    props_path = build_props(project, run_id, audio_path, duration_ms, cues, scenes, recordings, run_dir)

    output_path = run_dir / "final" / "video.mp4"
    if should_render:
        render(props_path, output_path)

    report = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "duration_ms": duration_ms,
        "subtitle_count": len(cues),
        "scene_count": len(scenes),
        "recordings": {key: str(value) for key, value in recordings.items()},
        "remotion_props": str(props_path),
        "final_video": str(output_path) if should_render else None,
    }
    write_json(run_dir / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the minimal agent-driven video pipeline")
    parser.add_argument("project", type=Path)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.project, should_render=not args.no_render), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
