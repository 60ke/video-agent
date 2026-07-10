from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from PIL import Image, ImageOps


DEFAULT_CONFIG = Path("config") / "gpt_image.local.json"
DEFAULT_SIZE = "1024x1792"
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
RESULT_STEPS = {"result_crop", "result_export", "result_gallery", "result_page"}
SITE_CAPTURE_TYPES = {"网站主页截图", "功能入口截图", "参数面板截图"}
GPT_IMAGE_MAX_ATTEMPTS = 8
GPT_IMAGE_RETRY_INTERVAL_SECONDS = 8
GPT_IMAGE_PROVIDER_COOLDOWN_SECONDS = 45


@dataclass(frozen=True)
class GPTImageProvider:
    name: str
    base_url: str
    api_key: str
    edit_path: str = "/v1/images/edits"
    model: str = "gpt-image-2"
    quality: str = "low"
    size: str = DEFAULT_SIZE
    timeout_seconds: int = 600
    weight: int = 1


@dataclass
class GPTImageConfig:
    providers: list[GPTImageProvider]
    strategy: str = "weighted_failover"
    max_attempts: int = GPT_IMAGE_MAX_ATTEMPTS
    retry_interval_seconds: float = GPT_IMAGE_RETRY_INTERVAL_SECONDS
    provider_cooldown_seconds: float = GPT_IMAGE_PROVIDER_COOLDOWN_SECONDS
    _rr_index: int = 0
    _cooldown_until: dict[str, float] | None = None

    @property
    def base_url(self) -> str:
        return self.providers[0].base_url if self.providers else ""

    @property
    def api_key(self) -> str:
        return self.providers[0].api_key if self.providers else ""

    @property
    def edit_path(self) -> str:
        return self.providers[0].edit_path if self.providers else "/v1/images/edits"

    @property
    def model(self) -> str:
        return self.providers[0].model if self.providers else "gpt-image-2"

    @property
    def quality(self) -> str:
        return self.providers[0].quality if self.providers else "low"

    @property
    def size(self) -> str:
        return self.providers[0].size if self.providers else DEFAULT_SIZE

    @property
    def timeout_seconds(self) -> int:
        return self.providers[0].timeout_seconds if self.providers else 600

    def provider_summary(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "max_attempts": self.max_attempts,
            "retry_interval_seconds": self.retry_interval_seconds,
            "provider_cooldown_seconds": self.provider_cooldown_seconds,
            "providers": [
                {
                    "name": provider.name,
                    "base_url": provider.base_url,
                    "edit_path": provider.edit_path,
                    "model": provider.model,
                    "quality": provider.quality,
                    "size": provider.size,
                    "weight": provider.weight,
                }
                for provider in self.providers
            ],
        }


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _provider_from_dict(item: dict[str, Any], *, defaults: dict[str, Any], index: int) -> GPTImageProvider:
    api_key = str(item.get("api_key") or defaults.get("api_key") or "").strip()
    base_url = str(item.get("base_url") or defaults.get("base_url") or "").strip()
    if not api_key or not base_url:
        raise ValueError(f"GPT image provider[{index}] requires api_key and base_url")
    name = str(item.get("name") or f"provider_{index + 1}").strip() or f"provider_{index + 1}"
    weight = int(item.get("weight") or defaults.get("weight") or 1)
    return GPTImageProvider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        edit_path=str(item.get("edit_path") or defaults.get("edit_path") or "/v1/images/edits"),
        model=str(item.get("model") or defaults.get("model") or "gpt-image-2"),
        quality=str(item.get("quality") or defaults.get("quality") or "low"),
        size=str(item.get("size") or defaults.get("size") or DEFAULT_SIZE),
        timeout_seconds=int(item.get("timeout_seconds") or defaults.get("timeout_seconds") or 600),
        weight=max(1, weight),
    )


def load_config(path: Path) -> GPTImageConfig:
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        raise ValueError(f"GPT image config must be a JSON object: {path}")

    defaults = {
        "api_key": str(payload.get("api_key") or os.getenv("GPT_IMAGE_API_KEY") or "").strip(),
        "base_url": str(payload.get("base_url") or os.getenv("GPT_IMAGE_BASE_URL") or "").strip(),
        "edit_path": str(payload.get("edit_path") or "/v1/images/edits"),
        "model": str(payload.get("model") or "gpt-image-2"),
        "quality": str(payload.get("quality") or "low"),
        "size": str(payload.get("size") or DEFAULT_SIZE),
        "timeout_seconds": int(payload.get("timeout_seconds") or 600),
        "weight": 1,
    }

    providers_raw = payload.get("providers")
    providers: list[GPTImageProvider] = []
    if isinstance(providers_raw, list) and providers_raw:
        for idx, item in enumerate(providers_raw):
            if not isinstance(item, dict):
                raise ValueError(f"GPT image providers[{idx}] must be an object")
            providers.append(_provider_from_dict(item, defaults=defaults, index=idx))
    else:
        api_key = defaults["api_key"]
        base_url = defaults["base_url"] or "https://maasapi.casdao.com"
        if not api_key:
            raise ValueError(f"GPT image api_key is missing; write it to {path} or GPT_IMAGE_API_KEY")
        providers.append(
            GPTImageProvider(
                name=str(payload.get("name") or "default"),
                base_url=base_url,
                api_key=api_key,
                edit_path=defaults["edit_path"],
                model=defaults["model"],
                quality=defaults["quality"],
                size=defaults["size"],
                timeout_seconds=defaults["timeout_seconds"],
                weight=1,
            )
        )

    strategy = str(payload.get("strategy") or "weighted_failover").strip() or "weighted_failover"
    return GPTImageConfig(
        providers=providers,
        strategy=strategy,
        max_attempts=int(payload.get("max_attempts") or GPT_IMAGE_MAX_ATTEMPTS),
        retry_interval_seconds=float(payload.get("retry_interval_seconds") or GPT_IMAGE_RETRY_INTERVAL_SECONDS),
        provider_cooldown_seconds=float(payload.get("provider_cooldown_seconds") or GPT_IMAGE_PROVIDER_COOLDOWN_SECONDS),
        _cooldown_until={},
    )


def dry_run_config() -> GPTImageConfig:
    return GPTImageConfig(
        providers=[
            GPTImageProvider(
                name="dry-run",
                base_url="dry-run",
                api_key="dry-run",
                edit_path="/dry-run",
                model="dry-run",
            )
        ],
        strategy="weighted_failover",
    )


def bearer(api_key: str) -> str:
    return api_key if " " in api_key.strip() else f"Bearer {api_key.strip()}"


def edit_url(provider: GPTImageProvider) -> str:
    return urljoin(provider.base_url.rstrip("/") + "/", provider.edit_path.lstrip("/"))


def content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "image/png"


class GPTImageRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, provider: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


def _httpx_client(*, timeout: float | httpx.Timeout) -> httpx.Client:
    # Provider IP allowlists require the machine's direct egress IP.
    # Explicitly disable env/system proxies for GPT image calls.
    return httpx.Client(timeout=timeout, trust_env=False, proxy=None)


def decode_image_response(response: httpx.Response) -> bytes:
    status_code = int(response.status_code)
    try:
        body = response.json()
    except ValueError as exc:
        raise GPTImageRequestError(
            f"GPT image response is not JSON: HTTP {status_code}",
            status_code=status_code,
        ) from exc
    if status_code < 200 or status_code >= 300:
        error = body.get("error") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise GPTImageRequestError(
            str(message or f"GPT image HTTP {status_code}"),
            status_code=status_code,
        )
    if not isinstance(body, dict):
        raise GPTImageRequestError("GPT image response root is not an object", status_code=status_code)
    items = body.get("data")
    if not isinstance(items, list) or not items:
        raise GPTImageRequestError("GPT image response has no data items", status_code=status_code)
    first = next((item for item in items if isinstance(item, dict)), None)
    if not first:
        raise GPTImageRequestError("GPT image response data item is invalid", status_code=status_code)
    b64_json = str(first.get("b64_json") or "").strip()
    if b64_json:
        return base64.b64decode(b64_json)
    url = str(first.get("url") or "").strip()
    if url:
        with _httpx_client(timeout=120) as client:
            downloaded = client.get(url)
        if downloaded.status_code < 200 or downloaded.status_code >= 300:
            raise GPTImageRequestError(
                f"failed to download GPT image result: HTTP {downloaded.status_code}",
                status_code=int(downloaded.status_code),
            )
        return downloaded.content
    raise GPTImageRequestError("GPT image response has no b64_json or url", status_code=status_code)


def is_success_status(status_code: int | None) -> bool:
    return status_code is not None and 200 <= int(status_code) < 300


def should_failover_provider(exc: BaseException, status_code: int | None = None) -> bool:
    """Failover on any non-success outcome.

    Rule: only a completed 2xx response with a valid image is success.
    Network failures, non-2xx HTTP, and 2xx responses that cannot be decoded
    all switch to another provider.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    if isinstance(exc, GPTImageRequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if status_code is None else status_code
        return not is_success_status(code)
    if status_code is not None:
        return not is_success_status(status_code)
    return True


def _mark_provider_cooldown(config: GPTImageConfig, provider: GPTImageProvider, *, status_code: int | None) -> None:
    if config._cooldown_until is None:
        config._cooldown_until = {}
    # Auth/quota/forbidden style codes get a longer cooldown; rate-limit/5xx stay short.
    hard = status_code in {401, 402, 403, 404} or (status_code is not None and 400 <= int(status_code) < 500 and status_code not in {408, 425, 429})
    cooldown = 3600.0 if hard else max(0.0, float(config.provider_cooldown_seconds))
    config._cooldown_until[provider.name] = time.time() + cooldown


def _available_providers(config: GPTImageConfig) -> list[GPTImageProvider]:
    now = time.time()
    cooldown = config._cooldown_until or {}
    available = [provider for provider in config.providers if float(cooldown.get(provider.name) or 0) <= now]
    return available or list(config.providers)


def _select_provider(config: GPTImageConfig, *, prefer_not: str | None = None) -> GPTImageProvider:
    candidates = _available_providers(config)
    if prefer_not and len(candidates) > 1:
        filtered = [provider for provider in candidates if provider.name != prefer_not]
        if filtered:
            candidates = filtered
    if not candidates:
        raise RuntimeError("no GPT image providers configured")

    if config.strategy == "round_robin":
        index = config._rr_index % len(candidates)
        config._rr_index += 1
        return candidates[index]

    # Default: weighted_failover — expand by weight, then round-robin across the expanded list.
    expanded: list[GPTImageProvider] = []
    for provider in candidates:
        expanded.extend([provider] * max(1, int(provider.weight)))
    index = config._rr_index % len(expanded)
    config._rr_index += 1
    return expanded[index]


def _post_gpt_edit(provider: GPTImageProvider, image_path: Path, prompt: str) -> bytes:
    data = {"model": provider.model, "prompt": prompt, "quality": provider.quality, "n": "1"}
    if provider.size:
        data["size"] = provider.size
    image_bytes = image_path.read_bytes()
    files = {"image": (image_path.name, image_bytes, content_type(image_path))}
    headers = {"Authorization": bearer(provider.api_key)}
    url = edit_url(provider)
    with _httpx_client(timeout=provider.timeout_seconds) as client:
        response = client.post(url, data=data, files=files, headers=headers)
    try:
        return decode_image_response(response)
    except GPTImageRequestError as exc:
        raise GPTImageRequestError(str(exc), status_code=exc.status_code, provider=provider.name) from None


def gpt_edit_image(config: GPTImageConfig, image_path: Path, prompt: str, raw_output: Path) -> None:
    if not config.providers:
        raise RuntimeError("no GPT image providers configured")
    last_exc: Exception | None = None
    last_provider_name: str | None = None
    max_attempts = max(1, int(config.max_attempts))
    for attempt in range(1, max_attempts + 1):
        provider = _select_provider(config, prefer_not=last_provider_name)
        last_provider_name = provider.name
        try:
            payload = _post_gpt_edit(provider, image_path, prompt)
            raw_output.parent.mkdir(parents=True, exist_ok=True)
            raw_output.write_bytes(payload)
            return
        except Exception as exc:  # noqa: BLE001 - failover on any non-success provider outcome
            last_exc = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
            status_code = None
            if isinstance(exc, GPTImageRequestError):
                status_code = exc.status_code
            elif isinstance(exc, httpx.HTTPStatusError):
                status_code = exc.response.status_code
            failover = should_failover_provider(last_exc, status_code)
            if failover:
                _mark_provider_cooldown(config, provider, status_code=status_code)
            remaining_providers = [item.name for item in _available_providers(config) if item.name != provider.name]
            can_switch = bool(remaining_providers)
            if attempt >= max_attempts or not failover:
                raise last_exc from None
            if not can_switch and status_code is not None and 400 <= int(status_code) < 500 and status_code not in {408, 425, 429}:
                # No alternate provider left for a hard client error.
                raise last_exc from None
            wait_seconds = float(config.retry_interval_seconds)
            action = "switching provider" if can_switch else "retrying same pool"
            code_text = str(status_code) if status_code is not None else "network"
            print(
                f"GPT image request failed via {provider.name} "
                f"(attempt {attempt}/{max_attempts}, status={code_text}): {last_exc}; "
                f"{action} and waiting {wait_seconds:.0f}s",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    if last_exc:
        raise last_exc


def preprocess_for_gpt(source_path: Path, output_path: Path, *, result: bool) -> Path:
    if not result:
        return source_path
    normalized_source = source_path.as_posix().lower()
    if "/assets/results/" in normalized_source:
        return source_path
    image = Image.open(source_path).convert("RGB")
    width, height = image.size
    work = image
    # Result pages often include browser chrome, dark canvas, and assistant widgets.
    # Keep the generated board/result as the model input and remove floating UI widgets
    # that are not part of the generated result.
    if width / max(height, 1) > 1.2:
        left = int(width * 0.36)
        top = int(height * 0.22)
        right = int(width * 0.93)
        bottom = height
        work = work.crop((left, top, right, bottom))
    elif height / max(width, 1) > 1.2:
        left = int(width * 0.06)
        top = int(height * 0.33)
        right = int(width * 0.90)
        bottom = int(height * 0.64)
        work = work.crop((left, top, right, bottom))
    draw_color = (248, 248, 248)
    w, h = work.size
    mask_box = (int(w * 0.70), int(h * 0.42), int(w * 0.94), int(h * 0.70))
    if mask_box[2] > mask_box[0] and mask_box[3] > mask_box[1]:
        patch = Image.new("RGB", (mask_box[2] - mask_box[0], mask_box[3] - mask_box[1]), draw_color)
        work.paste(patch, (mask_box[0], mask_box[1]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work.save(output_path, "PNG")
    return output_path


def normalize_to_video_canvas(input_path: Path, output_path: Path) -> dict[str, Any]:
    image = Image.open(input_path).convert("RGB")
    fitted = ImageOps.contain(image, (TARGET_WIDTH, TARGET_HEIGHT), method=Image.Resampling.LANCZOS)
    background = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (248, 248, 248))
    background.paste(fitted, ((TARGET_WIDTH - fitted.width) // 2, (TARGET_HEIGHT - fitted.height) // 2))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    background.save(output_path, "PNG")
    return probe_image(output_path)


def upsert_by_id(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    item_id = item.get("id")
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item_id:
            items[idx] = item
            return
    items.append(item)


def upsert_resource_by_asset_id(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    asset_id = item.get("asset_id")
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("asset_id") == asset_id:
            items[idx] = item
            return
    items.append(item)


def probe_image(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
    return {
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 6) if height else None,
        "probe_ok": True,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else case_dir / path


def as_case_relative(case_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(case_dir.resolve(strict=False)).as_posix()


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in project.get("assets", []) if isinstance(asset, dict) and asset.get("id")}


def resource_by_asset(case_dir: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(case_dir / "image_resources.json", {"resources": []})
    resources = payload.get("resources", []) if isinstance(payload, dict) else []
    return {str(item.get("asset_id")): item for item in resources if isinstance(item, dict) and item.get("asset_id")}


def is_result_event(event: dict[str, Any], source_asset: dict[str, Any], resource: dict[str, Any]) -> bool:
    evidence = str(event.get("evidence_binding") or "").lower()
    image_resource = source_asset.get("image_resource", {}) if isinstance(source_asset.get("image_resource"), dict) else {}
    step = str(resource.get("workflow_step") or image_resource.get("workflow_step") or "").lower()
    role = str(source_asset.get("role") or "").lower()
    source = str(source_asset.get("source") or "").replace("\\", "/").lower()
    return evidence in {"real_result", "real_generated_result"} or step in RESULT_STEPS or "result" in role or "assets/results/" in source


def is_site_screenshot_asset(source_asset: dict[str, Any], resource: dict[str, Any]) -> bool:
    origin = str(source_asset.get("origin") or resource.get("origin") or "").lower()
    source = str(source_asset.get("source") or resource.get("source") or "").replace("\\", "/").lower()
    capture_type = str(resource.get("capture_type") or source_asset.get("site_asset", {}).get("capture_type") or "")
    return origin == "site_screenshot_library" or "assets/sites/" in source or capture_type in SITE_CAPTURE_TYPES


def site_capture_type(source_asset: dict[str, Any], resource: dict[str, Any]) -> str:
    site_asset = source_asset.get("site_asset", {}) if isinstance(source_asset.get("site_asset"), dict) else {}
    return str(resource.get("capture_type") or site_asset.get("capture_type") or "")


def feature_context(source_asset: dict[str, Any], resource: dict[str, Any]) -> dict[str, Any]:
    site_asset = source_asset.get("site_asset", {}) if isinstance(source_asset.get("site_asset"), dict) else {}
    feature_path = resource.get("feature_path") or site_asset.get("feature_path") or []
    feature_label = str(resource.get("feature_label") or site_asset.get("feature_label") or "")
    parent_feature_label = str(resource.get("parent_feature_label") or site_asset.get("parent_feature_label") or "")
    if not feature_label and isinstance(feature_path, list) and feature_path:
        feature_label = str(feature_path[-1])
    return {
        "feature_path": [str(value) for value in feature_path if str(value).strip()] if isinstance(feature_path, list) else [],
        "feature_label": feature_label,
        "parent_feature_label": parent_feature_label,
        "is_graphic_ad_child": parent_feature_label == "图文广告" or (isinstance(feature_path, list) and "图文广告" in feature_path),
    }


def annotation_style_prompt() -> str:
    return (
        "Use an elegant product-demo annotation style instead of plain red rectangles: a rounded cyan-blue luminous outline, "
        "soft translucent spotlight wash, subtle corner ticks, and a tiny clean label tag when helpful. The annotation should feel like a polished SaaS demo callout. "
        "Do not use thick red boxes, multiple tiny circles, rough hand-drawn marks, or clutter. Do not cover important Chinese UI text. "
        "Use at most one primary highlight region, plus one tiny click dot if it helps show the action."
    )


def site_annotation_task(capture_type: str, source_asset: dict[str, Any], resource: dict[str, Any]) -> str:
    context = feature_context(source_asset, resource)
    feature_label = context["feature_label"]
    path_text = " -> ".join(context["feature_path"])
    style = annotation_style_prompt()
    source_hint = " ".join(
        str(value or "")
        for value in (
            capture_type,
            source_asset.get("id"),
            source_asset.get("source"),
            source_asset.get("description"),
            resource.get("description"),
            path_text,
        )
    )
    homepage_like = any(token in source_hint.lower() for token in ("主页", "首页", "home", "homepage"))
    if capture_type == "功能入口截图" and context["is_graphic_ad_child"]:
        return (
            f"This is a feature-entry screenshot for the nested path {path_text}. The target is the 图文广告 child item named {feature_label} "
            "inside the secondary submenu panel, not the parent 图文广告 row and not a homepage card. Preserve the UI exactly, fit the page into a vertical 9:16 keyframe, "
            f"and add one tasteful designed callout around only that child submenu item. {style}"
        )
    if capture_type == "功能入口截图":
        return (
            f"This is a feature-entry screenshot for {path_text}. The target is the hover/dropdown menu item named {feature_label} inside the opened 文生图 menu, "
            "not the top feature card pill/chip with the same label. Preserve the UI exactly, fit the page into a vertical 9:16 keyframe, "
            f"and add one tasteful designed callout around the correct dropdown item. {style}"
        )
    if capture_type == "参数面板截图":
        return (
            f"This is the parameter-panel screenshot for {path_text}. Highlight the whole parameter section as one larger readable region: from the section title/属性 header "
            "through the main required input rows, dropdown rows, and the core form card. Do not mark individual labels one by one. Do not make tiny circles. "
            "The highlight should frame the complete parameter area similarly to a green review box, but in a polished cyan/blue demo style. "
            "Keep upload boxes, field labels, dropdown controls, and the lower text area readable, with safe space for subtitles near the bottom. "
            f"{style}"
        )
    if capture_type == "网站主页截图" or homepage_like:
        return (
            "This is the website homepage screenshot. Highlight the 文生图 entry/card area as the starting point of the workflow while keeping the homepage overview readable. "
            f"{style}"
        )
    return (
        f"This is a website screenshot for {path_text}. Preserve the UI exactly and add one tasteful designed callout to the main functional target implied by the filename. {style}"
    )


def prompt_for(
    event: dict[str, Any],
    source_asset: dict[str, Any],
    resource: dict[str, Any],
    result: bool,
    site_screenshot: bool,
) -> str:
    visible_text = ", ".join(str(v) for v in (source_asset.get("visible_text") or resource.get("visible_text") or []) if v)
    description = str(source_asset.get("description") or resource.get("description") or "").strip()
    capture_type = site_capture_type(source_asset, resource)
    feature_context_data = feature_context(source_asset, resource)
    feature_path = feature_context_data["feature_path"]
    feature_path_text = " -> ".join(str(v) for v in feature_path if v)
    base = (
        "Use the uploaded image as the only source of truth. Create one vertical 9:16 keyframe for a 1080x1920 short video. "
        "Only adjust format, framing, scale, spacing, and composition so it can be placed directly in a vertical video. "
        "Do not create different content. Do not invent new UI, logos, products, text, colors, icons, or extra product details. "
        "Preserve the original Chinese text and visual meaning as much as possible. Keep the main subject centered and readable, "
        "with clean top and bottom safe space for subtitles. No decorative title cards and no marketing copy."
    )
    if site_screenshot:
        task = (
            "This is a real website screenshot. Preserve the website UI, Chinese text, menu structure, colors, and layout exactly. "
            "Compose it into a vertical 9:16 keyframe for a product demo. Do not invent or rewrite website content. "
            "Do not crop into a tiny local detail; keep enough surrounding context for the viewer to understand where they are. "
            + site_annotation_task(capture_type, source_asset, resource)
        )
    elif result:
        task = (
            "This is a business design result display frame. If the source contains a website result page, extract and re-layout only the visible generated result board/image content from that page; "
            "the webpage chrome is evidence only and should not be the final subject. Preserve the result exactly; do not redesign the brand board."
        )
    else:
        task = (
            "This is a function/process screenshot frame. Preserve the website UI state exactly, but reframe it as an AI-verified 9:16 screenshot: "
            "the active menu, form, button, or loading state must be large enough to read in the central safe region."
        )
    path_context = f" Feature path: {feature_path_text}." if feature_path_text else ""
    context = f" Source description: {description}" if description else ""
    text = f" Visible text to preserve: {visible_text}" if visible_text else ""
    return f"{base} {task}{path_context}{context}{text}"


def unique_keyframe_requests(project: dict[str, Any], case_dir: Path) -> list[dict[str, Any]]:
    assets = asset_index(project)
    resources = resource_by_asset(case_dir)
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, bool]] = set()
    for event in project.get("visual_track", []):
        if not isinstance(event, dict):
            continue
        asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
        if not asset_ids:
            continue
        for asset_id in asset_ids:
            source_asset = assets.get(asset_id)
            if not source_asset or str(source_asset.get("type") or "").lower() != "image":
                continue
            origin = str(source_asset.get("origin") or "").lower()
            image_resource = source_asset.get("image_resource", {}) if isinstance(source_asset.get("image_resource"), dict) else {}
            workflow_step = str(image_resource.get("workflow_step") or "").lower()
            if origin in {"gpt_image_site_keyframe", "gpt_image_layout_optimization"} or workflow_step in {
                "prepared_site_keyframe",
                "prepared_9x16",
            }:
                continue
            resource = resources.get(str(source_asset.get("id")), {})
            result = is_result_event(event, source_asset, resource)
            site_screenshot = is_site_screenshot_asset(source_asset, resource)
            key = (str(source_asset.get("id")), result)
            if key in seen:
                continue
            seen.add(key)
            requests.append(
                {
                    "event": event,
                    "asset": source_asset,
                    "resource": resource,
                    "result": result,
                    "site_screenshot": site_screenshot,
                }
            )
    return requests


def make_asset(
    case_dir: Path,
    source_asset: dict[str, Any],
    event: dict[str, Any],
    output_path: Path,
    metadata: dict[str, Any],
    result: bool,
    site_screenshot: bool,
) -> dict[str, Any]:
    old_id = str(source_asset.get("id"))
    workflow_step = "result_crop" if result else ("prepared_site_keyframe" if site_screenshot else "prepared_9x16")
    source_image_resource = source_asset.get("image_resource", {}) if isinstance(source_asset.get("image_resource"), dict) else {}
    source_workflow_step = str(source_image_resource.get("workflow_step") or "").strip()
    origin = "gpt_image_site_keyframe" if site_screenshot else "gpt_image_layout_optimization"
    role = "gpt_result_keyframe" if result else ("gpt_site_keyframe" if site_screenshot else "gpt_function_keyframe")
    id_prefix = "gpt_site_keyframe" if site_screenshot else "gpt_keyframe"
    return {
        "id": f"asset_{id_prefix}_{old_id}",
        "type": "image",
        "source": as_case_relative(case_dir, output_path),
        "relative_source": as_case_relative(case_dir, output_path),
        "filename": output_path.name,
        "mime_type": "image/png",
        "origin": origin,
        "source_asset_id": old_id,
        "role": role,
        "description": source_asset.get("description") or "",
        "visible_text": source_asset.get("visible_text") or [],
        "supported_claims": source_asset.get("supported_claims") or [],
        "metadata": metadata,
        "display_risk": [],
        "layout_plan": {
            "primary_display_mode": "result-showcase" if result else "portrait-showcase",
            "focus_region": "ai_verified_full_frame",
            "fill_strategy": "direct_1080x1920_keyframe",
            "min_subject_frame_ratio": 0.55,
            "source_display_mode": source_image_resource.get("workflow_step") or "",
        },
        "site_asset": source_asset.get("site_asset", {}) if isinstance(source_asset.get("site_asset"), dict) else {},
        "image_resource": {
            "workflow_step": workflow_step,
            "source_workflow_step": source_workflow_step,
            "variant": "gpt_image_site_keyframe" if site_screenshot else "gpt_image_layout_optimized",
            "source_asset_id": old_id,
            "ai_verified_for_video": True,
        },
        "quality": {"readable": True, "contains_private_info": False, "needs_review": False, "ai_verified": True},
    }


def make_image_resource(
    new_asset: dict[str, Any],
    source_asset: dict[str, Any],
    source_resource: dict[str, Any],
    result: bool,
    site_screenshot: bool,
    callouts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_id = str(source_asset.get("id") or "")
    new_id = str(new_asset.get("id") or "")
    layout_plan = new_asset.get("layout_plan", {}) if isinstance(new_asset.get("layout_plan"), dict) else {}
    quality = new_asset.get("quality", {}) if isinstance(new_asset.get("quality"), dict) else {}
    feature_path = source_resource.get("feature_path") or new_asset.get("site_asset", {}).get("feature_path") or []
    workflow_step = "result_crop" if result else ("prepared_site_keyframe" if site_screenshot else "prepared_9x16")
    return {
        "id": f"img_{new_id}",
        "asset_id": new_id,
        "filename": new_asset.get("filename"),
        "source": new_asset.get("source"),
        "type": "image",
        "feature_id": source_resource.get("feature_id") or new_asset.get("site_asset", {}).get("feature_id") or "",
        "feature_label": source_resource.get("feature_label") or new_asset.get("site_asset", {}).get("feature_label") or "",
        "feature_path": feature_path,
        "source_module_id": source_resource.get("source_module_id") or new_asset.get("site_asset", {}).get("module_id") or "",
        "source_module_label": source_resource.get("source_module_label") or new_asset.get("site_asset", {}).get("module_label") or "",
        "parent_feature_id": source_resource.get("parent_feature_id") or new_asset.get("site_asset", {}).get("parent_feature_id") or "",
        "parent_feature_label": source_resource.get("parent_feature_label") or new_asset.get("site_asset", {}).get("parent_feature_label") or "",
        "workflow_step": workflow_step,
        "source_workflow_step": source_resource.get("workflow_step") or new_asset.get("image_resource", {}).get("source_workflow_step") or "",
        "capture_type": source_resource.get("capture_type") or new_asset.get("site_asset", {}).get("capture_type") or "",
        "variant": new_asset.get("image_resource", {}).get("variant") or "gpt_image_layout_optimized",
        "origin": new_asset.get("origin"),
        "capture_method": "gpt_image_edit",
        "page_url": source_resource.get("page_url") or new_asset.get("site_asset", {}).get("route") or "",
        "title": f"AI优化关键帧-{source_resource.get('title') or new_asset.get('filename')}",
        "description": new_asset.get("description") or source_resource.get("description") or "",
        "visible_text": new_asset.get("visible_text") or source_resource.get("visible_text") or [],
        "prompt_inputs": source_resource.get("prompt_inputs") if isinstance(source_resource.get("prompt_inputs"), dict) else {},
        "callouts": callouts if callouts is not None else (source_resource.get("callouts") if isinstance(source_resource.get("callouts"), list) else []),
        "relations": {
            "source_asset_id": source_id,
            "source_resource_id": source_resource.get("id") or "",
        },
        "supported_claims": new_asset.get("supported_claims") or source_resource.get("supported_claims") or [],
        "recommended_usage": ["preferred_video_keyframe", "direct_9x16"] + (
            ["result_showcase"] if result else ["process_proof", "site_flow"]
        ),
        "quality": quality,
        "layout_plan": layout_plan,
    }


def register_prepared_assets(case_dir: Path, new_assets: list[dict[str, Any]], new_resources: list[dict[str, Any]]) -> None:
    manifest_path = case_dir / "asset_manifest.json"
    resources_path = case_dir / "image_resources.json"
    manifest = load_json(manifest_path, {"schema_version": 1, "status": "registered", "assets": []})
    image_resources = load_json(resources_path, {"schema_version": 1, "status": "ready", "resources": []})
    if not isinstance(manifest.get("assets"), list):
        manifest["assets"] = []
    if not isinstance(image_resources.get("resources"), list):
        image_resources["resources"] = []
    for asset in new_assets:
        upsert_by_id(manifest["assets"], asset)
    for resource in new_resources:
        upsert_resource_by_asset_id(image_resources["resources"], resource)
    manifest["status"] = "registered"
    manifest["asset_count"] = len(manifest["assets"])
    image_resources["status"] = "ready" if image_resources["resources"] else "pending"
    write_json(manifest_path, manifest)
    write_json(resources_path, image_resources)


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path)
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is invalid: {project_path}")
    requests = unique_keyframe_requests(project, case_dir)
    if args.limit:
        requests = requests[: args.limit]
    needs_gpt_image = bool(requests)
    config = dry_run_config() if (args.dry_run or not needs_gpt_image) else load_config(Path(args.config).expanduser().resolve(strict=False))
    if not requests:
        output_project = Path(args.output_project).expanduser().resolve(strict=False) if args.output_project else case_dir / "video_project.gpt_image.json"
        write_json(output_project, project)
        report_path = case_dir / "output" / "reports" / "gpt_image_keyframes_report.json"
        write_json(
            report_path,
            {
                "schema_version": 1,
                "provider": config.provider_summary(),
                "project": str(output_project),
                "registered_assets": [],
                "registered_resources": [],
                "items": [],
                "status": "skipped_no_unprepared_image_assets",
            },
        )
        return {"ok": True, "code": "ok", "reason": "", "data": {"project": str(output_project), "report": str(report_path), "count": 0}}

    replacement_by_source: dict[str, str] = {}
    site_replaced_visual_ids: set[str] = set()
    new_assets: list[dict[str, Any]] = []
    new_resources: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    raw_dir = case_dir / "output" / "gpt_image_keyframes" / "raw"
    preprocessed_dir = case_dir / "output" / "gpt_image_keyframes" / "preprocessed"
    prepared_root = case_dir / "assets" / "prepared" / "keyframes"
    site_prepared_root = case_dir / "assets" / "prepared" / "site_keyframes"
    result_root = case_dir / "assets" / "results" / "gpt_keyframes"

    for item in requests:
        event = item["event"]
        source_asset = item["asset"]
        source_id = str(source_asset.get("id"))
        result = bool(item["result"])
        site_screenshot = bool(item["site_screenshot"])
        source_path = resolve_case_path(case_dir, source_asset.get("source"))
        if not source_path or not source_path.is_file():
            raise FileNotFoundError(f"source asset missing: {source_asset.get('source')}")
        stem = f"{source_id}"
        preprocessed_path = preprocessed_dir / f"{stem}_input.png"
        raw_path = raw_dir / f"{stem}_raw.png"
        if result:
            final_root = result_root
        elif site_screenshot:
            final_root = site_prepared_root
        else:
            final_root = prepared_root
        final_path = final_root / f"{stem}_{'site_9x16' if site_screenshot else 'gpt_9x16'}.png"
        prompt = prompt_for(event, source_asset, item["resource"], result, site_screenshot)
        transformed_callouts: list[dict[str, Any]] | None = None
        if args.force or site_screenshot or not final_path.is_file():
            gpt_input = preprocess_for_gpt(source_path, preprocessed_path, result=result)
            if args.dry_run:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(gpt_input.read_bytes())
            else:
                gpt_edit_image(config, gpt_input, prompt, raw_path)
            metadata = normalize_to_video_canvas(raw_path, final_path)
        else:
            metadata = probe_image(final_path)
        if site_screenshot:
            metadata["prepared_by"] = "gpt_image_site_annotation" if not args.dry_run else "dry_run_site_canvas"
            metadata["annotation_policy"] = "baked_into_gpt_image_keyframe"
            transformed_callouts = []
        new_asset = make_asset(case_dir, source_asset, event, final_path, metadata, result, site_screenshot)
        new_resource = make_image_resource(new_asset, source_asset, item["resource"], result, site_screenshot, callouts=transformed_callouts)
        replacement_by_source[source_id] = new_asset["id"]
        new_assets.append(new_asset)
        new_resources.append(new_resource)
        report_items.append(
            {
                "source_asset_id": source_id,
                "new_asset_id": new_asset["id"],
                "result_visual": result,
                "site_screenshot": site_screenshot,
                "capture_type": site_capture_type(source_asset, item["resource"]),
                "source": source_asset.get("source"),
                "preprocessed_input": as_case_relative(case_dir, preprocessed_path) if result else source_asset.get("source"),
                "raw_output": as_case_relative(case_dir, raw_path),
                "prepared_output": new_asset["source"],
                "prepared_by": "gpt_image",
                "prompt": prompt,
                "metadata": metadata,
            }
        )

    existing_assets = [asset for asset in project.get("assets", []) if isinstance(asset, dict)]
    for asset in new_assets:
        upsert_by_id(existing_assets, asset)
    project["assets"] = existing_assets
    new_asset_by_id = {asset["id"]: asset for asset in new_assets}
    for event in project.get("visual_track", []):
        if not isinstance(event, dict):
            continue
        asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
        mapped_asset_ids = [replacement_by_source.get(asset_id, asset_id) for asset_id in asset_ids]
        if mapped_asset_ids != asset_ids:
            first_replacement = mapped_asset_ids[0]
            if any(asset_id in replacement_by_source and new_asset_by_id.get(replacement_by_source[asset_id], {}).get("origin") == "gpt_image_site_keyframe" for asset_id in asset_ids):
                if event.get("id"):
                    site_replaced_visual_ids.add(str(event["id"]))
            prepared_layout = (
                "result-showcase"
                if new_asset_by_id.get(first_replacement, {}).get("role") == "gpt_result_keyframe"
                else "portrait-showcase"
            )
            event["asset_ids"] = mapped_asset_ids
            if len(mapped_asset_ids) == 1:
                event["layout"] = prepared_layout
                event["display_mode"] = prepared_layout
            event.setdefault("qa_expectations", {})["uses_gpt_image_prepared_keyframe"] = True
    if site_replaced_visual_ids and isinstance(project.get("overlay_track"), list):
        project["overlay_track"] = [
            overlay
            for overlay in project["overlay_track"]
            if not (isinstance(overlay, dict) and str(overlay.get("target_visual_id") or "") in site_replaced_visual_ids)
        ]

    if not args.dry_run:
        register_prepared_assets(case_dir, new_assets, new_resources)

    output_project = Path(args.output_project).expanduser().resolve(strict=False) if args.output_project else case_dir / "video_project.gpt_image.json"
    write_json(output_project, project)
    report_path = case_dir / "output" / "reports" / "gpt_image_keyframes_report.json"
    write_json(
        report_path,
        {
            "schema_version": 1,
            "provider": config.provider_summary(),
            "project": str(output_project),
            "registered_assets": [] if args.dry_run else [asset["id"] for asset in new_assets],
            "registered_resources": [] if args.dry_run else [resource["id"] for resource in new_resources],
            "items": report_items,
        },
    )
    return {"ok": True, "code": "ok", "reason": "", "data": {"project": str(output_project), "report": str(report_path), "count": len(report_items)}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare GPT image optimized 9:16 keyframes for a Pipeline V2 video project.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--output-project")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Do not call GPT image; copy sources through the same project rewrite path.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}
    if args.json:
        sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    elif output["ok"]:
        print(f"GPT image keyframes: {output['data']['project']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
