from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_RISK_TERMS = ("科幻熊猫", "AI")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_join(segments: list[dict[str, Any]]) -> str:
    parts = []
    for seg in segments:
        text = str(seg.get("text") or "").strip()
        if text:
            parts.append(text)
    if not parts:
        raise ValueError("video_script.json has no segment text")
    return "".join(parts)


def detect_high_risk_terms(text: str, explicit: list[str]) -> list[str]:
    terms: list[str] = []
    for term in list(DEFAULT_RISK_TERMS) + explicit:
        if term and term in text and term not in terms:
            terms.append(term)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+-]*", text):
        if token not in terms:
            terms.append(token)
    return terms


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    script = load_json(case_dir / "video_script.json")
    segments = script.get("segments", [])
    if not isinstance(segments, list):
        raise ValueError("video_script.segments must be a list")

    text = normalize_join([seg for seg in segments if isinstance(seg, dict)])
    high_risk = detect_high_risk_terms(text, list(args.high_risk_term or []) + list(script.get("high_risk_terms", [])))
    plan = {
        "schema_version": 1,
        "status": "ready",
        "text": text,
        "segments": [
            {
                "script_segment_id": seg.get("id"),
                "text": seg.get("text"),
                "duration_hint": seg.get("duration_hint"),
            }
            for seg in segments
            if isinstance(seg, dict)
        ],
        "high_risk_terms": high_risk,
        "char_count": len("".join(text.split())),
        "speed_policy": {
            "ideal_min": 4.8,
            "ideal_max": 6.2,
            "hard_min": 4.2,
            "hard_max": 7.0
        }
    }
    output_path = case_dir / "voice_plan.json"
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": plan | {"voice_plan": str(output_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create voice_plan.json from video_script.json.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--high-risk-term", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Voice plan: {output['data']['voice_plan']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
