"""Run Stage7 local four-script acceptance and write a ledger."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from video_agent.io import utc_now, write_json_atomic


SCRIPTS = (
    ("test1.txt", "stage7_accept_local_test1i"),
    ("test2.txt", "stage7_accept_local_test2j"),
    ("test3.txt", "stage7_accept_local_test3j"),
    ("test4.txt", "stage7_accept_local_test4i"),
)


def _existing_success(case_dir: Path) -> dict | None:
    runs_dir = case_dir / "runs"
    if not runs_dir.is_dir():
        return None
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        video = run_dir / "final" / "video.mp4"
        cover = run_dir / "final" / "cover.png"
        if video.is_file() and cover.is_file():
            return {
                "run_id": run_dir.name,
                "final_video": video.as_posix(),
                "final_cover": cover.as_posix(),
            }
    return None


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    results: list[dict] = []
    for script_name, case_id in SCRIPTS:
        script = root / "文案" / script_name
        case_dir = root / "cases" / case_id
        existing = _existing_success(case_dir) if case_dir.exists() else None
        if existing is not None:
            entry = {
                "script": script_name,
                "case_id": case_id,
                "status": "passed",
                "reused_existing": True,
                **existing,
            }
            results.append(entry)
            print("REUSE", case_id, "passed", flush=True)
            continue
        if case_dir.exists():
            results.append(
                {
                    "script": script_name,
                    "case_id": case_id,
                    "status": "failed",
                    "message": f"case exists without final deliverables: {case_dir}",
                }
            )
            print("RESULT", case_id, "failed", flush=True)
            continue
        cmd = [
            sys.executable,
            "main.py",
            "generate-video",
            "--script",
            str(script),
            "--case-id",
            case_id,
            "--json",
        ]
        print("RUN", " ".join(cmd), flush=True)
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = None
        stdout = (proc.stdout or "").strip()
        if stdout:
            try:
                start = stdout.rfind("{")
                payload = json.loads(stdout[start:]) if start >= 0 else None
            except json.JSONDecodeError:
                payload = None
        ok = proc.returncode == 0 and isinstance(payload, dict) and bool(payload.get("ok"))
        entry = {
            "script": script_name,
            "case_id": case_id,
            "status": "passed" if ok else "failed",
            "returncode": proc.returncode,
            "payload": payload,
            "stderr_tail": (proc.stderr or "")[-2000:],
            "stdout_tail": stdout[-2000:],
        }
        if ok and payload:
            entry["run_id"] = payload.get("run_id")
            entry["final_video"] = payload.get("final_video")
            entry["final_cover"] = payload.get("final_cover")
        results.append(entry)
        print("RESULT", case_id, entry["status"], flush=True)

    report = {
        "schema_version": "v4.stage7_local_scripts_acceptance.1",
        "generated_at": utc_now(),
        "bgm_enabled": False,
        "notes": {
            "theme_park_asset": "asset://A0293 from 美陈/主题公园.png",
            "category_fallback": {"文生图/雕塑小品": "文生图/景观小品"},
        },
        "passed": all(item["status"] == "passed" for item in results),
        "results": results,
    }
    out = root / "tests" / "fixtures" / "v4" / "stage7" / "local_scripts_acceptance_ledger.json"
    write_json_atomic(out, report)
    print(json.dumps({"ok": report["passed"], "output": out.as_posix()}, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
