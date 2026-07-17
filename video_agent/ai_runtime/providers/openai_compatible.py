from __future__ import annotations

from typing import Any

import httpx

from video_agent.ai_runtime.contracts import ProviderProfile, ProviderRequest, ProviderResponse
from video_agent.ai_runtime.errors import AITransportError


class OpenAICompatibleProvider:
    def __init__(self, client: httpx.AsyncClient, profile: ProviderProfile) -> None:
        self.client = client
        self.profile = profile

    @property
    def endpoint(self) -> str:
        base = self.profile.base_url.rstrip("/")
        return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"

    async def complete_json(self, request: ProviderRequest) -> ProviderResponse:
        if "json" not in f"{request.system_prompt}\n{request.input_payload}".lower():
            raise AITransportError("JSON mode requires the prompt to explicitly request JSON")
        payload: dict[str, Any] = {
            "model": request.model_profile.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": _compact_json(request.input_payload)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": request.model_profile.max_tokens,
        }
        if request.model_profile.temperature is not None:
            payload["temperature"] = request.model_profile.temperature
        if request.model_profile.thinking is not None:
            payload["thinking"] = {"type": "enabled" if request.model_profile.thinking else "disabled"}
        try:
            response = await self.client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.profile.api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise AITransportError("provider returned empty JSON content")
        except AITransportError:
            raise
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            message = f"provider request failed{f' with HTTP {status}' if status else ''}: {exc}"
            raise AITransportError(message) from exc
        return ProviderResponse(
            content=content,
            raw_body=body,
            request_id=response.headers.get("x-request-id") or body.get("id"),
            usage=body.get("usage") if isinstance(body.get("usage"), dict) else {},
        )


def _compact_json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
