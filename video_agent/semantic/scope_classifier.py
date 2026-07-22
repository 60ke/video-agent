from __future__ import annotations

from pathlib import Path

from video_agent.ai_runtime import AsyncModelGateway, StructuredInvocation, TraceContext
from video_agent.contracts.v4 import ArtifactEnvelope, VideoScope
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistrySnapshot

from .prompts import load_scope_prompt
from .deterministic_scope_repair import normalize_video_scope
from .registry_payload import scope_categories_payload
from .validation import validate_video_scope


async def classify_video_scope(
    *,
    gateway: AsyncModelGateway,
    repo_root: Path,
    run_id: str,
    frozen_narration: str,
    registry: CapabilityRegistrySnapshot,
    trace_dir: Path,
) -> tuple[ArtifactEnvelope[VideoScope], StructuredInvocation[VideoScope]]:
    prompt = load_scope_prompt(repo_root)
    narration_fingerprint = sha256_json({"text": frozen_narration})
    registry_payload = scope_categories_payload(registry)
    input_payload = {
        "request_id": f"scope_{run_id}",
        "frozen_narration": {
            "text": frozen_narration,
            "source_fingerprint": f"sha256:{narration_fingerprint}",
        },
        "enabled_categories": registry_payload,
    }
    def validator(value: VideoScope) -> None:
        repaired = normalize_video_scope(value)
        value.scope_mode = repaired.scope_mode
        value.categories = repaired.categories
        validate_video_scope(
            value,
            frozen_narration=frozen_narration,
            registry=registry,
            primary_required=_has_explicit_primary(frozen_narration),
        )

    invocation = await gateway.invoke_structured(
        capability="scope_classifier",
        system_prompt=prompt.system_prompt,
        input_payload=input_payload,
        output_type=VideoScope,
        trace_context=TraceContext(
            output_dir=trace_dir,
            prompt_version=prompt.version,
            prompt_fingerprint=prompt.fingerprint,
        ),
        domain_validator=validator,
    )
    envelope = ArtifactEnvelope[VideoScope](
        schema_version="v4.video_scope.1",
        input_fingerprints={
            "frozen_narration": narration_fingerprint,
            "category_registry": sha256_json(registry_payload),
            "prompt": prompt.fingerprint,
            "request": invocation.request_fingerprint,
        },
        payload=invocation.value,
    )
    return envelope, invocation


def _has_explicit_primary(text: str) -> bool:
    return any(marker in text for marker in ("为例", "举例", "重点", "主要"))
