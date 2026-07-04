from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "http://192.168.2.191:9890/api/v1/digital-human/voice-clones/generate"


def read_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    voice_plan = Path(args.case) / "voice_plan.json"
    if voice_plan.is_file():
        data = json.loads(voice_plan.read_text(encoding="utf-8"))
        text = data.get("text") or data.get("source_text")
        if text:
            return str(text).strip()
    raise ValueError("voice text is required: pass --text, --text-file, or create voice_plan.json")


def ffprobe_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nk=1:nw=1",
        str(path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def maybe_json(path: Path) -> dict[str, Any] | None:
    raw = path.read_bytes()
    stripped = raw.lstrip()
    if not stripped.startswith(b"{"):
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _find_first(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value:
                return value
            found = _find_first(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_first(item, keys)
            if found:
                return found
    return None


def materialize_json_audio(response: dict[str, Any], output_path: Path) -> str:
    url = _find_first(response, {"audio_url", "file_url", "url", "download_url"})
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        with urllib.request.urlopen(url, timeout=120) as handle:  # noqa: S310 - user-configured local service.
            output_path.write_bytes(handle.read())
        return "download_url"

    b64 = _find_first(response, {"audio_base64", "base64", "data"})
    if isinstance(b64, str):
        if "," in b64 and b64.split(",", 1)[0].startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            output_path.write_bytes(base64.b64decode(b64))
            return "base64"
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"failed to decode audio base64: {exc}") from exc

    raise ValueError("voice API returned JSON but no supported audio url/base64 field was found")


def call_voice_api(endpoint: str, prompt_audio: Path, text: str, output_path: Path, response_path: Path) -> str:
    if not prompt_audio.is_file():
        raise FileNotFoundError(f"prompt audio not found: {prompt_audio}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_output = Path(temp_dir) / "voice_response.bin"
        cmd = [
            "curl.exe",
            "--location",
            endpoint,
            "--form",
            f"prompt_audio=@{prompt_audio}",
            "--form",
            f"text={text}",
            "--output",
            str(temp_output),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"voice API request failed: {proc.stderr.strip()}")

        json_response = maybe_json(temp_output)
        if json_response is not None:
            response_path.write_text(json.dumps(json_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return materialize_json_audio(json_response, output_path)

        shutil.copy2(temp_output, output_path)
        response_path.write_text(
            json.dumps({"type": "raw_audio", "endpoint": endpoint}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return "raw_audio"


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")

    text = read_text(args)
    prompt_audio = Path(args.prompt_audio).expanduser().resolve(strict=False) if args.prompt_audio else case_dir / "audio" / "voice_prompt_5s.wav"
    output_path = Path(args.output).expanduser().resolve(strict=False) if args.output else case_dir / "audio" / "voice.wav"
    response_path = case_dir / "output" / "voice_clone" / "voice_response.json"
    response_path.parent.mkdir(parents=True, exist_ok=True)

    source = call_voice_api(args.endpoint, prompt_audio, text, output_path, response_path)
    duration = ffprobe_duration(output_path)
    if duration is None:
        raise RuntimeError(f"generated voice is not probeable audio: {output_path}")

    report = {
        "schema_version": 1,
        "engine": "voice_clone_api",
        "endpoint": args.endpoint,
        "prompt_audio": str(prompt_audio),
        "text": text,
        "audio_path": str(output_path),
        "response_path": str(response_path),
        "response_type": source,
        "duration": duration,
        "chars": len(text),
        "chars_per_second": round(len(text) / duration, 3) if duration > 0 else None,
    }
    report_path = case_dir / "output" / "voice_clone" / "voice_clone_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": report | {"report_path": str(report_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate case voice audio with the configured voice clone API.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--prompt-audio")
    parser.add_argument("--output")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must report structured failure.
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Generated voice: {output['data']['audio_path']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
