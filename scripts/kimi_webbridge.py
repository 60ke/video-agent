from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "http://127.0.0.1:10086/command"


def load_args(value: str | None, args_file: str | None) -> dict[str, Any]:
    if args_file:
        data = json.loads(Path(args_file).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("--args-file JSON root must be an object")
        return data
    if not value:
        return {}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("--args JSON root must be an object")
    return data


def post_command(endpoint: str, session: str, action: str, command_args: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "action": action,
        "args": command_args,
        "session": session,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Kimi WebBridge request failed: {exc}") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"raw": text}
    if not isinstance(parsed, dict):
        parsed = {"value": parsed}
    return parsed


def run(args: argparse.Namespace) -> dict[str, Any]:
    command_args = load_args(args.args, args.args_file)
    result = post_command(args.endpoint, args.session, args.action, command_args)
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "endpoint": args.endpoint,
            "session": args.session,
            "action": args.action,
            "result": result,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call Kimi WebBridge without PowerShell JSON quoting issues.")
    parser.add_argument("--action", required=True, help="WebBridge action, e.g. navigate, snapshot, click, fill, screenshot.")
    parser.add_argument("--args", help="JSON object string for action args.")
    parser.add_argument("--args-file", help="Path to a JSON object for action args.")
    parser.add_argument("--session", default="kehuanxiongmao-demo")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must return structured errors.
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}

    if args.json or not output["ok"]:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output["data"]["result"], ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
