from __future__ import annotations

import base64
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx

from video_agent.io import load_json


@dataclass(frozen=True)
class ImageProvider:
    name: str
    base_url: str
    api_key: str
    model: str
    edit_path: str
    quality: str
    size: str
    timeout_seconds: float
    weight: int
    max_retries: int


@dataclass(frozen=True)
class ImageEditResult:
    content: bytes
    provider: str
    model: str
    response_id: str | None


def _providers(repo_root: Path) -> list[ImageProvider]:
    path = repo_root / "config" / "gpt_image.local.json"
    payload = load_json(path) if path.is_file() else {}
    defaults = {
        "base_url": payload.get("base_url") or os.getenv("GPT_IMAGE_BASE_URL"),
        "api_key": payload.get("api_key") or os.getenv("GPT_IMAGE_API_KEY"),
        "model": payload.get("model") or "gpt-image-2",
        "edit_path": payload.get("edit_path") or "/v1/images/edits",
        "quality": payload.get("quality") or "low",
        "size": payload.get("size") or "1024x1792",
        "timeout_seconds": payload.get("timeout_seconds") or 600,
        "max_retries": payload.get("max_retries") if payload.get("max_retries") is not None else 2,
    }
    raw_items = payload.get("providers") or [payload]
    result: list[ImageProvider] = []
    for index, item in enumerate(raw_items):
        base_url = str(item.get("base_url") or defaults["base_url"] or "").strip()
        api_key = str(item.get("api_key") or defaults["api_key"] or "").strip()
        if not base_url or not api_key:
            continue
        result.append(
            ImageProvider(
                name=str(item.get("name") or f"provider_{index + 1}"),
                base_url=base_url,
                api_key=api_key,
                model=str(item.get("model") or defaults["model"]),
                edit_path=str(item.get("edit_path") or defaults["edit_path"]),
                quality=str(item.get("quality") or defaults["quality"]),
                size=str(item.get("size") or defaults["size"]),
                timeout_seconds=float(item.get("timeout_seconds") or defaults["timeout_seconds"]),
                weight=max(1, int(item.get("weight") or 1)),
                max_retries=max(0, int(item.get("max_retries", defaults["max_retries"]))),
            )
        )
    if not result:
        raise ValueError("GPT Image key missing in config/gpt_image.local.json or environment")
    return result


def _decode(response: httpx.Response) -> tuple[bytes, str | None]:
    response.raise_for_status()
    body = response.json()
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise RuntimeError("GPT Image response has no image data")
    item = items[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), body.get("id")
    if item.get("url"):
        with httpx.Client(timeout=120, trust_env=False) as client:
            downloaded = client.get(str(item["url"]))
            downloaded.raise_for_status()
            return downloaded.content, body.get("id")
    raise RuntimeError("GPT Image response has neither b64_json nor url")


def edit_image(repo_root: Path, source: Path, prompt: str, *, size: str | None = None) -> ImageEditResult:
    errors: list[str] = []
    providers = sorted(_providers(repo_root), key=lambda provider: provider.weight, reverse=True)
    for provider in providers:
        url = urljoin(provider.base_url.rstrip("/") + "/", provider.edit_path.lstrip("/"))
        headers = {"Authorization": f"Bearer {provider.api_key}"}
        data = {"model": provider.model, "prompt": prompt, "size": size or provider.size, "quality": provider.quality}
        for attempt in range(provider.max_retries + 1):
            try:
                with source.open("rb") as handle, httpx.Client(
                    timeout=provider.timeout_seconds, trust_env=False
                ) as client:
                    response = client.post(
                        url,
                        headers=headers,
                        data=data,
                        files={"image": (source.name, handle, mimetypes.guess_type(source.name)[0] or "image/png")},
                    )
                content, response_id = _decode(response)
                return ImageEditResult(
                    content=content,
                    provider=provider.name,
                    model=provider.model,
                    response_id=response_id,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    f"{provider.name}[{attempt + 1}/{provider.max_retries + 1}]:"
                    f"{exc.__class__.__name__}:{exc}"
                )
                if attempt >= provider.max_retries or not _is_retryable(exc):
                    break
                time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("all GPT Image providers failed: " + " | ".join(errors))


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status in {408, 409, 425, 429} or status >= 500
    return False
