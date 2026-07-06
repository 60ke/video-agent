from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from utils.skill_path import require_skill_root


RUNTIME_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
RUNTIME_SUFFIXES = {".pyc", ".pyo", ".tmp", ".temp"}
GENERATED_MEDIA_SUFFIXES = {".mp4", ".mov", ".wav", ".mp3", ".m4a", ".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_SKILL_MEDIA_PREFIXES = (
    Path("assets") / "outro",
)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _relative(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def check_skill_hygiene(skill_root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for path in skill_root.rglob("*"):
        rel = _relative(path, skill_root)
        if any(part in RUNTIME_DIR_NAMES for part in rel.parts):
            errors.append(f"runtime cache inside skill package: {rel}")
            continue
        if path.is_file() and path.suffix.lower() in RUNTIME_SUFFIXES:
            errors.append(f"runtime file inside skill package: {rel}")
        if path.is_file() and path.suffix.lower() in GENERATED_MEDIA_SUFFIXES:
            allowed = any(_is_relative_to(rel, prefix) for prefix in ALLOWED_SKILL_MEDIA_PREFIXES)
            if not allowed:
                warnings.append(f"media file inside skill package outside assets allowlist: {rel}")

    return errors, warnings


def check_case_hygiene(case_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not case_dir.is_dir():
        return [f"case directory missing: {case_dir}"], warnings

    expected_dirs = [
        "assets",
        "assets/browser",
        "assets/browser/raw",
        "assets/browser/annotated",
        "assets/results",
        "audio",
        "output",
        "output/minimax",
        "output/versions",
        "output/qa",
        "output/reports",
    ]
    for rel in expected_dirs:
        if not (case_dir / rel).is_dir():
            errors.append(f"missing case directory: {rel}")

    for path in case_dir.rglob("*"):
        rel = _relative(path, case_dir)
        if any(part in RUNTIME_DIR_NAMES for part in rel.parts):
            errors.append(f"runtime cache inside case: {rel}")
        if path.is_file() and path.suffix.lower() in RUNTIME_SUFFIXES:
            errors.append(f"runtime file inside case: {rel}")

    versions = case_dir / "output" / "versions"
    if versions.is_dir():
        names: set[str] = set()
        for file in versions.glob("*"):
            if not file.is_file():
                continue
            lowered = file.name.lower()
            if lowered in names:
                errors.append(f"case-insensitive duplicate output version name: {file.name}")
            names.add(lowered)
        final = versions / "final.mp4"
        if final.exists():
            warnings.append("output/versions/final.mp4 is generic; prefer versioned labels to avoid overwriting accepted renders")

    return errors, warnings


def run(case_dir: Path | None, check_skill: bool) -> dict[str, object]:
    skill_root = require_skill_root(Path(__file__).resolve())
    errors: list[str] = []
    warnings: list[str] = []

    if check_skill:
        skill_errors, skill_warnings = check_skill_hygiene(skill_root)
        errors.extend(skill_errors)
        warnings.extend(skill_warnings)

    if case_dir:
        case_errors, case_warnings = check_case_hygiene(case_dir.resolve(strict=False))
        errors.extend(case_errors)
        warnings.extend(case_warnings)

    ok = not errors
    return {
        "ok": ok,
        "code": "ok" if ok else "hygiene_failed",
        "reason": "" if ok else f"{len(errors)} hygiene error(s)",
        "data": {
            "skill_root": str(skill_root),
            "case_dir": str(case_dir.resolve(strict=False)) if case_dir else None,
            "errors": errors,
            "warnings": warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check video-agent skill/case hygiene.")
    parser.add_argument("--case", help="Optional case directory to check.")
    parser.add_argument("--skip-skill", action="store_true", help="Do not check skill package hygiene.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(Path(args.case).expanduser() if args.case else None, not args.skip_skill)
    except Exception as exc:  # noqa: BLE001 - CLI must report structured failure.
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {"errors": [str(exc)], "warnings": []},
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print("Hygiene check passed")
    else:
        print(output["reason"], file=sys.stderr)
        for error in output["data"].get("errors", []):
            print(f"- {error}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
