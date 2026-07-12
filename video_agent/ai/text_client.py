from __future__ import annotations

import json
import os
import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from video_agent.io import load_json


class OpenAICompatibleTextClient:
    def __init__(self, repo_root: Path) -> None:
        path = repo_root / "config" / "ai.local.json"
        config = load_json(path) if path.is_file() else {}
        self.base_url = str(os.getenv("VIDEO_AGENT_AI_BASE_URL") or config.get("base_url") or "").rstrip("/")
        self.api_key = str(os.getenv("VIDEO_AGENT_AI_API_KEY") or config.get("api_key") or "")
        self.model = str(config.get("model") or "gpt-5")
        if not self.base_url or not self.api_key:
            raise ValueError("AI planner config missing; create config/ai.local.json or provide locked narration")

    def complete_json(self, system: str, user: str, schema_name: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=180.0) as client:
            response = client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{schema_name} planner returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError(f"{schema_name} planner must return a JSON object")
        return result

    def complete_json_with_images(self, system: str, user: str, images: list[Path], schema_name: str) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for path in images:
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=240.0) as client:
            response = client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        try:
            result = json.loads(body["choices"][0]["message"]["content"])
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"{schema_name} critic returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError(f"{schema_name} critic must return a JSON object")
        return result
