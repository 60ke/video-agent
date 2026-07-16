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
        self.coarse_model = str(config.get("coarse_model") or "deepseek-v4-flash")
        self.max_tokens = int(config.get("max_tokens") or 8192)
        if not self.base_url or not self.api_key:
            raise ValueError("AI planner config missing; create config/ai.local.json or provide locked narration")

    def complete_json(
        self,
        system: str,
        user: str,
        schema_name: str,
        *,
        max_tokens: int | None = None,
        model: str | None = None,
        thinking: bool | None = None,
    ) -> dict[str, Any]:
        if "json" not in f"{system}\n{user}".lower():
            raise ValueError("DeepSeek JSON Output requires the prompt to explicitly contain the word JSON")
        endpoint = f"{self.base_url}/chat/completions" if self.base_url.endswith("/v1") else f"{self.base_url}/v1/chat/completions"
        last_error: Exception | None = None
        for attempt in range(3):
            retry_note = "\n重要：必须返回一个非空的 JSON 对象，不要输出解释或 Markdown。" if attempt else ""
            payload = {
                "model": model or self.model,
                "messages": [
                    {"role": "system", "content": system + retry_note},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens or self.max_tokens,
            }
            if thinking is not None:
                payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
            try:
                with httpx.Client(timeout=240.0) as client:
                    response = client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=payload,
                    )
                if response.is_error:
                    raise ValueError(
                        f"{schema_name} planner request failed: HTTP {response.status_code}: {response.text[:1000]}"
                    )
                body = response.json()
                content = body["choices"][0]["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError(f"{schema_name} planner returned empty content")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError(f"{schema_name} planner must return a JSON object")
                return result
            except (KeyError, json.JSONDecodeError, ValueError, httpx.HTTPError) as exc:
                last_error = exc
        raise ValueError(f"{schema_name} planner failed after 3 JSON Output attempts: {last_error}") from last_error

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
