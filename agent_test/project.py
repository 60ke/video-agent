from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_START = "<!-- VO_START -->"
SCRIPT_END = "<!-- VO_END -->"


@dataclass(frozen=True)
class ProjectFiles:
    root: Path
    config: Path
    brief: Path
    script: Path
    storyboard_md: Path
    storyboard_json: Path
    capture_inventory: Path
    style: Path
    work: Path
    renders: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectFiles":
        root = root.resolve()
        return cls(
            root=root,
            config=root / "project.json",
            brief=root / "BRIEF.md",
            script=root / "SCRIPT.md",
            storyboard_md=root / "STORYBOARD.md",
            storyboard_json=root / "storyboard.json",
            capture_inventory=root / "capture" / "inventory.json",
            style=root / "STYLE.md",
            work=root / "work",
            renders=root / "renders",
        )


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    match = re.match(r"\A---\s*\n.*?\n---\s*\n", text, flags=re.DOTALL)
    return text[match.end() :] if match else text


def read_locked_script(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if SCRIPT_START in text and SCRIPT_END in text:
        body = text.split(SCRIPT_START, 1)[1].split(SCRIPT_END, 1)[0]
        script = body.strip()
    else:
        body = _strip_frontmatter(text)
        lines = [line.strip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        script = "".join(lines).strip()
    if not script:
        raise ValueError(f"SCRIPT.md contains no narration: {path}")
    return script


def create_project(root: Path, *, title: str, script: str = "") -> ProjectFiles:
    files = ProjectFiles.from_root(root)
    if files.root.exists() and any(files.root.iterdir()):
        raise FileExistsError(f"project directory is not empty: {files.root}")
    files.root.mkdir(parents=True, exist_ok=True)
    (files.root / "recipes").mkdir()
    (files.root / "assets").mkdir()
    (files.root / "capture").mkdir()
    files.work.mkdir()
    files.renders.mkdir()

    write_json(
        files.config,
        {
            "title": title,
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "mode": "autonomous",
            "tts": {"speed": 1.0},
            "recipes": {},
            "result_assets": [],
        },
    )
    files.brief.write_text(
        f"# Brief\n\n- product: {title}\n- audience: 待补充\n- goal: 产品功能演示\n- format: 1080x1920\n- length: 约 30 秒\n- mode: autonomous\n- promise: 待补充\n- proof: 待补充\n- cta: 待补充\n",
        encoding="utf-8",
    )
    files.script.write_text(
        "# Script\n\n" + SCRIPT_START + "\n" + script.strip() + "\n" + SCRIPT_END + "\n",
        encoding="utf-8",
    )
    files.storyboard_md.write_text("# Storyboard\n\n待 Agent 生成。\n", encoding="utf-8")
    files.storyboard_json.write_text(
        json.dumps({"arc": "demo_loop", "video_direction": {}, "beats": []}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files.style.write_text(
        "# Style\n\n- palette: source-derived or neutral dark\n- typography: bold display + readable body\n- motion: voice-paced, long-tail easing\n- captions: bottom safe-area pill\n",
        encoding="utf-8",
    )
    write_json(files.capture_inventory, {"recipes": [], "assets": [], "brand": {}})
    return files


def load_project(source: Path) -> tuple[dict[str, Any], ProjectFiles | None, str]:
    source = source.resolve()
    if source.is_dir():
        files = ProjectFiles.from_root(source)
        if not files.config.is_file():
            raise FileNotFoundError(files.config)
        if not files.script.is_file():
            raise FileNotFoundError(files.script)
        config = read_json(files.config)
        script = read_locked_script(files.script)
        return config, files, script
    if source.is_file():
        config = read_json(source)
        script = str(config.get("script") or "").strip()
        if not script:
            raise ValueError("legacy project JSON requires project.script")
        return config, None, script
    raise FileNotFoundError(source)


def build_capture_inventory(config: dict[str, Any], root: Path) -> dict[str, Any]:
    recipes = config.get("recipes") or {}
    result_assets = config.get("result_assets") or []
    if not isinstance(recipes, dict):
        raise ValueError("project.recipes must be an object")
    if not isinstance(result_assets, list):
        raise ValueError("project.result_assets must be a list")
    recipe_items: list[dict[str, Any]] = []
    for recipe_id, raw in recipes.items():
        if not isinstance(raw, (str, dict)):
            raise ValueError(f"invalid recipe value: {recipe_id}")
        recipe_items.append({"recipe_id": str(recipe_id), "source": raw if isinstance(raw, str) else "inline"})
    asset_items = []
    for raw in result_assets:
        value = str(raw)
        path = Path(value)
        resolved = path if path.is_absolute() else root / path
        asset_items.append({"path": value, "exists": resolved.is_file(), "kind": "result_image"})
    return {"recipes": recipe_items, "assets": asset_items, "brand": {"title": str(config.get("title") or "")}}


def validate_project(files: ProjectFiles, *, require_storyboard: bool = True) -> list[str]:
    errors: list[str] = []
    for path in (files.config, files.brief, files.script, files.style, files.capture_inventory):
        if not path.is_file():
            errors.append(f"missing: {path.relative_to(files.root)}")
    if require_storyboard:
        for path in (files.storyboard_md, files.storyboard_json):
            if not path.is_file():
                errors.append(f"missing: {path.relative_to(files.root)}")
    if files.script.is_file():
        try:
            read_locked_script(files.script)
        except Exception as exc:
            errors.append(str(exc))
    return errors
