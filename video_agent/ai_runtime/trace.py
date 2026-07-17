from __future__ import annotations

from pathlib import Path
from typing import Any

from video_agent.ai_runtime.contracts import TraceContext
from video_agent.io import load_json, utc_now, write_json_atomic


class InvocationTrace:
    def __init__(self, context: TraceContext) -> None:
        self.context = context
        self.context.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self.context.output_dir / "manifest.json"

    @property
    def validated_path(self) -> Path:
        return self.context.output_dir / "response.validated.json"

    def replay(self, request_fingerprint: str) -> dict[str, Any] | None:
        if not self.manifest_path.is_file() or not self.validated_path.is_file():
            return None
        manifest = load_json(self.manifest_path)
        if manifest.get("validation_status") != "validated" or manifest.get("request_fingerprint") != request_fingerprint:
            return None
        payload = load_json(self.validated_path)
        return payload if isinstance(payload, dict) else None

    def start(self, *, system_prompt: str, input_payload: dict[str, Any]) -> None:
        (self.context.output_dir / "request.system.md").write_text(system_prompt, encoding="utf-8", newline="\n")
        write_json_atomic(self.context.output_dir / "request.input.json", input_payload)

    def raw(self, *, content: str, body: dict[str, Any]) -> None:
        write_json_atomic(self.context.output_dir / "response.raw.json", {"content": content, "provider_body": body})

    def complete(self, *, validated: dict[str, Any], manifest: dict[str, Any]) -> None:
        write_json_atomic(self.validated_path, validated)
        write_json_atomic(self.manifest_path, {**manifest, "validation_status": "validated", "updated_at": utc_now()})

    def fail(self, *, manifest: dict[str, Any], failure_type: str, errors: list[dict[str, Any]]) -> None:
        write_json_atomic(
            self.manifest_path,
            {
                **manifest,
                "validation_status": "failed",
                "failure_type": failure_type,
                "validation_errors": errors,
                "updated_at": utc_now(),
            },
        )
