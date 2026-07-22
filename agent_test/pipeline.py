from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from agent_test.planner import ScenePlanner
from agent_test.subtitles import build_subtitle_cues
from video_agent.speech.minimax import normalize_tokens


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _duration_ms(path: Path) -> int:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-1000:]}")
    return round(float(result.stdout.strip()) * 1000)


def _resolve(repo_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (repo_root / path).resolve()


def _load_minimax_config(repo_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    local = repo_root / "config" / "minimax.local.json"
    if local.is_file():
        config.update(_read_json(local))
    project_config = project.get("tts")
    if isinstance(project_config, dict):
        config.update(project_config)
    config["api_key"] = (os.getenv("MINIMAX_API_KEY") or config.get("api_key") or "").strip()
    return config


def _synthesize_minimax(script: str, config: dict[str, Any], work_dir: Path) -> tuple[Path, list[dict[str, Any]], int]:
    api_key = str(config.get("api_key") or "").strip()
    voice_id = str(config.get("voice_id") or "").strip()
    if not api_key or not voice_id:
        raise ValueError("MiniMax requires api_key/MINIMAX_API_KEY and voice_id")
    endpoint = str(config.get("endpoint") or "https://api.minimaxi.com/v1/t2a_v2")
    payload = {
        "model": str(config.get("model") or "speech-02-hd"),
        "text": script,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(config.get("speed", 1.0)),
            "vol": float(config.get("vol", 1.0)),
            "pitch": int(config.get("pitch", 0)),
        },
        "audio_setting": {
            "sample_rate": int(config.get("sample_rate", 32000)),
            "bitrate": int(config.get("bitrate", 128000)),
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": True,
        "subtitle_type": "word",
    }
    emotion = str(config.get("emotion") or "").strip()
    if emotion:
        payload["voice_setting"]["emotion"] = emotion
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=180.0) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        base = body.get("base_resp") or {}
        if base.get("status_code") not in (0, None):
            raise RuntimeError(f"MiniMax API error: {base.get('status_msg')}")
        data = body.get("data") or {}
        audio_hex = data.get("audio")
        subtitle_url = data.get("subtitle_file")
        if not audio_hex or not subtitle_url:
            raise RuntimeError("MiniMax did not return audio and word subtitles")
        subtitle_response = client.get(subtitle_url)
        subtitle_response.raise_for_status()
        raw_subtitles = subtitle_response.json()

    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "voice.mp3"
    audio_path.write_bytes(bytes.fromhex(audio_hex))
    tokens = normalize_tokens(raw_subtitles)
    duration_ms = _duration_ms(audio_path)
    _write_json(
        work_dir / "minimax_response.json",
        {
            "trace_id": body.get("trace_id"),
            "request": {"model": payload["model"], "voice_setting": payload["voice_setting"], "text": script},
            "subtitle_file": subtitle_url,
            "subtitles": raw_subtitles,
        },
    )
    return audio_path, tokens, duration_ms


def _prepare_voice(repo_root: Path, project: dict[str, Any], run_dir: Path) -> tuple[Path, list[dict[str, Any]], int]:
    existing = project.get("existing_voice")
    if isinstance(existing, dict):
        audio_value = str(existing.get("audio") or "")
        tokens_value = str(existing.get("tokens") or "")
        if not audio_value or not tokens_value:
            raise ValueError("existing_voice requires audio and tokens")
        audio_path = _resolve(repo_root, audio_value)
        tokens_payload = _read_json(_resolve(repo_root, tokens_value))
        raw_tokens = tokens_payload.get("tokens")
        if not isinstance(raw_tokens, list):
            raise ValueError("existing voice token file must contain a tokens list")
        target = run_dir / "voice" / audio_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_path, target)
        return target, [item for item in raw_tokens if isinstance(item, dict)], _duration_ms(target)

    config = _load_minimax_config(repo_root, project)
    return _synthesize_minimax(str(project["script"]), config, run_dir / "voice")


def _record_recipes(
    repo_root: Path,
    project: dict[str, Any],
    scenes: list[dict[str, Any]],
    run_dir: Path,
) -> dict[str, Path]:
    recipes = project.get("recipes") or {}
    if not isinstance(recipes, dict):
        raise ValueError("recipes must be an object keyed by recipe_id")
    required = sorted({scene["recipe_id"] for scene in scenes if scene.get("kind") == "website_operation" and scene.get("recipe_id")})
    recordings: dict[str, Path] = {}
    for recipe_id in required:
        recipe_value = recipes.get(recipe_id)
        if isinstance(recipe_value, dict):
            recipe_path = run_dir / "recipes" / f"{recipe_id}.json"
            _write_json(recipe_path, recipe_value)
        elif isinstance(recipe_value, str):
            recipe_path = _resolve(repo_root, recipe_value)
        else:
            raise ValueError(f"invalid recipe: {recipe_id}")
        output_dir = run_dir / "recordings" / recipe_id
        command = [
            "node",
            str(repo_root / "cdp-capture" / "bin" / "agent-record.js"),
            "--recipe",
            str(recipe_path),
            "--output",
            str(output_dir),
        ]
        subprocess.run(command, cwd=repo_root / "cdp-capture", check=True)
        recording = output_dir / "recording.mp4"
        if not recording.is_file():
            raise RuntimeError(f"CDP recorder produced no MP4 for {recipe_id}")
        recordings[recipe_id] = recording
    return recordings


def _copy_public_asset(source: Path, public_dir: Path, name: str) -> str:
    suffix = source.suffix.lower() or ".bin"
    target = public_dir / f"{name}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(public_dir.parents[1]).as_posix()


def _build_remotion_props(
    repo_root: Path,
    project: dict[str, Any],
    run_id: str,
    audio_path: Path,
    duration_ms: int,
    cues: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    recordings: dict[str, Path],
) -> tuple[Path, dict[str, Any]]:
    fps = int(project.get("fps", 30))
    remotion_root = repo_root / "remotion"
    public_dir = remotion_root / "public" / "agent-test" / run_id
    public_dir.mkdir(parents=True, exist_ok=True)
    voice_public = _copy_public_asset(audio_path, public_dir, "voice")

    copied_images: dict[str, str] = {}
    copied_recordings: dict[str, str] = {}
    for recipe_id, path in recordings.items():
        copied_recordings[recipe_id] = _copy_public_asset(path, public_dir, f"recording-{recipe_id}")

    rendered_scenes: list[dict[str, Any]] = []
    for scene in scenes:
        sources: list[str] = []
        if scene["kind"] == "website_operation" and scene.get("recipe_id") in copied_recordings:
            sources = [copied_recordings[scene["recipe_id"]]]
        else:
            for index, raw in enumerate(scene.get("asset_paths") or []):
                source = _resolve(repo_root, raw)
                key = str(source)
                if key not in copied_images:
                    copied_images[key] = _copy_public_asset(source, public_dir, f"image-{len(copied_images) + 1:03d}")
                sources.append(copied_images[key])
        rendered_scenes.append({**scene, "sources": sources})

    props = {
        "width": int(project.get("width", 1080)),
        "height": int(project.get("height", 1920)),
        "fps": fps,
        "frame_count": max(round(duration_ms / 1000 * fps), 1),
        "voice_path": voice_public,
        "title": str(project.get("title") or "Agent Video Test"),
        "scenes": rendered_scenes,
        "subtitles": cues,
    }
    props_path = run_dir_from_public(public_dir, repo_root) / "remotion_props.json"
    _write_json(props_path, props)
    return props_path, props


def run_dir_from_public(public_dir: Path, repo_root: Path) -> Path:
    run_id = public_dir.name
    return repo_root / "agent_test_runs" / run_id


def _render(repo_root: Path, props_path: Path, output_path: Path) -> None:
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
    subprocess.run(command, cwd=repo_root / "remotion", check=True)


def run(project_path: Path, *, render: bool = True) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    project_path = project_path.resolve()
    project = _read_json(project_path)
    script = str(project.get("script") or "").strip()
    if not script:
        raise ValueError("project.script is required")

    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_dir = repo_root / "agent_test_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(project_path, run_dir / "project.json")

    audio_path, tokens, duration_ms = _prepare_voice(repo_root, project, run_dir)
    _write_json(run_dir / "timing_lock.json", {"duration_ms": duration_ms, "tokens": tokens})

    fps = int(project.get("fps", 30))
    cues = build_subtitle_cues(tokens, fps=fps)
    _write_json(run_dir / "subtitles.json", {"fps": fps, "cues": cues})

    recipes = project.get("recipes") or {}
    result_assets = [str(value) for value in project.get("result_assets") or []]
    scenes = ScenePlanner().plan(cues, recipes=recipes, result_assets=result_assets)
    _write_json(run_dir / "scene_plan.json", {"scenes": scenes})

    recordings = _record_recipes(repo_root, project, scenes, run_dir)
    props_path, props = _build_remotion_props(
        repo_root,
        project,
        run_id,
        audio_path,
        duration_ms,
        cues,
        scenes,
        recordings,
    )
    output_path = run_dir / "final" / "video.mp4"
    if render:
        _render(repo_root, props_path, output_path)

    report = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "duration_ms": duration_ms,
        "scene_count": len(scenes),
        "subtitle_count": len(cues),
        "recordings": {key: str(value) for key, value in recordings.items()},
        "remotion_props": str(props_path),
        "final_video": str(output_path) if render else None,
        "rendered": render,
        "frame_count": props["frame_count"],
    }
    _write_json(run_dir / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the minimal agent-driven video validation pipeline")
    parser.add_argument("project", type=Path, help="Path to agent-test project JSON")
    parser.add_argument("--no-render", action="store_true", help="Only produce timing, scene plan, recordings and props")
    args = parser.parse_args(argv)
    report = run(args.project, render=not args.no_render)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
