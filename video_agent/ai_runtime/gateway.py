from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from video_agent.contracts.v4.common import DomainValidationError
from video_agent.io import sha256_json, utc_now

from .contracts import (
    ModelProfile,
    ProviderRequest,
    StructuredInvocation,
    TraceContext,
)
from .errors import AIDomainError, AIJsonSyntaxError, AIRuntimeError, AISchemaError, AITransportError
from .providers.base import JSONProvider
from .routing import RuntimeConfiguration
from .trace import InvocationTrace


T = TypeVar("T", bound=BaseModel)
DomainValidator = Callable[[T], None]


class AsyncModelGateway:
    def __init__(self, configuration: RuntimeConfiguration, providers: dict[str, JSONProvider]) -> None:
        self.configuration = configuration
        self.providers = providers
        self.provider_semaphores = {
            key: asyncio.Semaphore(profile.max_concurrency)
            for key, profile in configuration.providers.items()
        }
        self.capability_semaphores = {
            key: asyncio.Semaphore(route.max_concurrency)
            for key, route in configuration.routes.items()
        }

    async def invoke_structured(
        self,
        *,
        capability: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_type: type[T],
        trace_context: TraceContext,
        domain_validator: DomainValidator[T] | None = None,
        route_kind: str = "primary",
    ) -> StructuredInvocation[T]:
        effective_system_prompt = _append_exact_output_contract(system_prompt, output_type)
        route = self.configuration.routes[capability]
        profile_id = getattr(route, route_kind)
        if not profile_id:
            raise ValueError(f"route {capability} does not define {route_kind}")
        model_profile = self.configuration.models[profile_id]
        provider = self.providers[model_profile.provider_profile]
        fingerprint = _request_fingerprint(
            capability=capability,
            system_prompt=effective_system_prompt,
            input_payload=input_payload,
            output_type=output_type,
            model_profile=model_profile,
            prompt_fingerprint=trace_context.prompt_fingerprint,
        )
        trace = InvocationTrace(trace_context)
        replay = trace.replay(fingerprint)
        if replay is not None:
            value = output_type.model_validate(replay)
            if domain_validator:
                domain_validator(value)
            return StructuredInvocation(
                value=value,
                request_fingerprint=fingerprint,
                model_profile=profile_id,
                replayed=True,
                raw_content=None,
            )

        started = time.perf_counter()
        trace.start(system_prompt=effective_system_prompt, input_payload=input_payload)
        base_manifest = {
            "capability": capability,
            "prompt_version": trace_context.prompt_version,
            "prompt_fingerprint": trace_context.prompt_fingerprint,
            "provider_profile": model_profile.provider_profile,
            "model_profile": profile_id,
            "model": model_profile.model,
            "request_fingerprint": fingerprint,
            "started_at": utc_now(),
            "repair_count": 0,
            "rebuild_count": 0,
        }
        try:
            response = await self._request_with_retry(
                provider=provider,
                request=ProviderRequest(
                    capability=capability,
                    system_prompt=effective_system_prompt,
                    input_payload=input_payload,
                    model_profile=model_profile,
                ),
                retries=route.max_transport_retries,
                provider_profile=model_profile.provider_profile,
                capability=capability,
            )
            trace.raw(content=response.content, body=response.raw_body)
            try:
                decoded = json.loads(response.content)
            except json.JSONDecodeError as exc:
                raise AIJsonSyntaxError(f"{capability} returned invalid JSON: {exc}") from exc
            if not isinstance(decoded, dict):
                raise AIJsonSyntaxError(f"{capability} must return one JSON object")
            try:
                value = output_type.model_validate(decoded)
            except ValidationError as exc:
                raise AISchemaError(
                    f"{capability} failed {output_type.__name__} schema",
                    details=exc.errors(include_url=False, include_input=False),
                ) from exc
            if domain_validator:
                try:
                    domain_validator(value)
                except DomainValidationError as exc:
                    raise AIDomainError(
                        str(exc),
                        details=[issue.model_dump(mode="json") for issue in exc.issues],
                    ) from exc
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            trace.complete(
                validated=value.model_dump(mode="json"),
                manifest={
                    **base_manifest,
                    "elapsed_ms": elapsed_ms,
                    "usage": response.usage,
                    "provider_request_id": response.request_id,
                },
            )
            return StructuredInvocation(
                value=value,
                request_fingerprint=fingerprint,
                model_profile=profile_id,
                replayed=False,
                raw_content=response.content,
            )
        except AIRuntimeError as exc:
            trace.fail(
                manifest={**base_manifest, "elapsed_ms": round((time.perf_counter() - started) * 1000)},
                failure_type=exc.failure_type,
                errors=exc.details or [{"message": str(exc)}],
            )
            raise

    async def _request_with_retry(
        self,
        *,
        provider: JSONProvider,
        request: ProviderRequest,
        retries: int,
        provider_profile: str,
        capability: str,
    ):
        last_error: AITransportError | None = None
        for attempt in range(retries + 1):
            try:
                async with self.provider_semaphores[provider_profile], self.capability_semaphores[capability]:
                    return await provider.complete_json(request)
            except AITransportError as exc:
                last_error = exc
                if attempt == retries:
                    raise
                await asyncio.sleep(min(2**attempt, 4))
        raise last_error or AITransportError("provider retry loop exited unexpectedly")


def _request_fingerprint(
    *,
    capability: str,
    system_prompt: str,
    input_payload: dict[str, Any],
    output_type: type[BaseModel],
    model_profile: ModelProfile,
    prompt_fingerprint: str | None,
) -> str:
    return sha256_json(
        {
            "capability": capability,
            "provider_profile": model_profile.provider_profile,
            "model_profile": model_profile.profile_id,
            "model": model_profile.model,
            "system_prompt": system_prompt,
            "prompt_fingerprint": prompt_fingerprint,
            "input_payload": input_payload,
            "output_schema": output_type.model_json_schema(),
            "settings": {
                "max_tokens": model_profile.max_tokens,
                "temperature": model_profile.temperature,
                "thinking": model_profile.thinking,
            },
        }
    )


def _append_exact_output_contract(system_prompt: str, output_type: type[BaseModel]) -> str:
    schema = json.dumps(output_type.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        system_prompt.rstrip()
        + "\n\n# Exact JSON Output Schema (Authoritative)\n"
        + "Return exactly one JSON object that validates against the schema below. "
        + "Do not add envelope fields, aliases, comments, Markdown fences, or properties "
        + "that are not declared by this schema. Every required property must be present.\n\n"
        + schema
        + "\n"
    )
