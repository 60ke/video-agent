from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_agent.ai_runtime import (
    AIDomainError,
    AIJsonSyntaxError,
    AISchemaError,
    AsyncModelGateway,
    StructuredInvocation,
    TraceContext,
)
from video_agent.ai_runtime.trace import InvocationTrace
from video_agent.contracts.v4 import ArtifactEnvelope, SceneSemanticPlan, VideoScope
from video_agent.contracts.v4.common import DomainValidationError, ValidationIssue
from video_agent.io import load_json, sha256_json, utc_now, write_json_atomic
from video_agent.registries import CapabilityRegistrySnapshot

from .deterministic_scene_repair import apply_deterministic_scene_repairs
from .prompts import load_scene_prompt
from .registry_payload import scene_registry_payload
from .repair import can_field_repair, request_field_repair
from .validation import validate_scene_semantic_plan


async def plan_scene_semantics(
    *,
    gateway: AsyncModelGateway,
    repo_root: Path,
    run_id: str,
    frozen_narration: str,
    video_scope: VideoScope,
    registry: CapabilityRegistrySnapshot,
    trace_dir: Path,
) -> tuple[ArtifactEnvelope[SceneSemanticPlan], StructuredInvocation[SceneSemanticPlan]]:
    registry_payload = scene_registry_payload(registry)
    prompt = load_scene_prompt(repo_root, registry_payload)
    narration_fingerprint = sha256_json({"text": frozen_narration})
    input_payload = {
        "request_id": f"scene_{run_id}",
        "frozen_narration": {
            "text": frozen_narration,
            "source_fingerprint": f"sha256:{narration_fingerprint}",
        },
        "video_scope": video_scope.model_dump(mode="json"),
        "registry_snapshot": registry_payload,
    }
    def validator(value: SceneSemanticPlan) -> None:
        repaired = apply_deterministic_scene_repairs(value)
        value.scenes = repaired.scenes
        validate_scene_semantic_plan(value, frozen_narration=frozen_narration, registry=registry)

    try:
        invocation = await gateway.invoke_structured(
            capability="scene_semantics",
            system_prompt=prompt.system_prompt,
            input_payload=input_payload,
            output_type=SceneSemanticPlan,
            trace_context=TraceContext(
                output_dir=trace_dir,
                prompt_version=prompt.version,
                prompt_fingerprint=prompt.fingerprint,
            ),
            domain_validator=validator,
        )
    except (AIDomainError, AISchemaError, AIJsonSyntaxError) as initial_error:
        invocation = await _recover_scene_plan(
            gateway=gateway,
            repo_root=repo_root,
            prompt_system=prompt.system_prompt,
            prompt_version=prompt.version,
            prompt_fingerprint=prompt.fingerprint,
            input_payload=input_payload,
            frozen_narration=frozen_narration,
            registry=registry,
            trace_dir=trace_dir,
            initial_error=initial_error,
        )
    envelope = ArtifactEnvelope[SceneSemanticPlan](
        schema_version="v4.scene_semantics.1",
        input_fingerprints={
            "frozen_narration": narration_fingerprint,
            "video_scope": sha256_json(video_scope),
            "registry": sha256_json(registry_payload),
            "prompt": prompt.fingerprint,
            "request": invocation.request_fingerprint,
        },
        payload=invocation.value,
    )
    return envelope, invocation


async def _recover_scene_plan(
    *,
    gateway: AsyncModelGateway,
    repo_root: Path,
    prompt_system: str,
    prompt_version: str,
    prompt_fingerprint: str,
    input_payload: dict[str, Any],
    frozen_narration: str,
    registry: CapabilityRegistrySnapshot,
    trace_dir: Path,
    initial_error: AIDomainError | AISchemaError | AIJsonSyntaxError,
) -> StructuredInvocation[SceneSemanticPlan]:
    route = gateway.configuration.routes["scene_semantics"]
    def validator(value: SceneSemanticPlan) -> None:
        repaired = apply_deterministic_scene_repairs(value)
        value.scenes = repaired.scenes
        validate_scene_semantic_plan(value, frozen_narration=frozen_narration, registry=registry)
    repair_count = 0
    payload = _raw_payload(trace_dir)
    current_error: Exception = initial_error
    if payload is not None and isinstance(initial_error, AIDomainError):
        for issue_payload in initial_error.details[: route.max_field_repairs]:
            issue = ValidationIssue.model_validate(issue_payload)
            if not can_field_repair(issue):
                break
            repair_count += 1
            payload = await request_field_repair(
                gateway=gateway,
                repo_root=repo_root,
                invalid_payload=payload,
                issue=issue,
                registry=registry,
                original_text=_scene_text_for_path(payload, issue.path, frozen_narration),
                trace_dir=trace_dir / "repairs" / f"field_{repair_count:02d}",
            )
            try:
                candidate = SceneSemanticPlan.model_validate(payload)
                validator(candidate)
                invocation = StructuredInvocation(
                    value=candidate,
                    request_fingerprint=_root_request_fingerprint(trace_dir),
                    model_profile=gateway.configuration.routes["scene_semantics"].repair or "semantic_fast",
                    replayed=False,
                    raw_content=json.dumps(payload, ensure_ascii=False),
                )
                _finalize_root_trace(trace_dir, candidate, repair_count=repair_count, rebuild_count=0)
                return invocation
            except (DomainValidationError, ValueError) as exc:
                current_error = exc

    if route.max_full_rebuilds < 1:
        raise current_error
    rebuild_prompt = (
        prompt_system
        + "\n\n# Full Rebuild Correction\n"
        + "上一次完整输出未通过 Contract。根据原始输入和以下错误重新输出完整 JSON，不得只输出补丁：\n"
        + json.dumps(_error_details(current_error), ensure_ascii=False, indent=2)
    )
    invocation = await gateway.invoke_structured(
        capability="scene_semantics",
        system_prompt=rebuild_prompt,
        input_payload=input_payload,
        output_type=SceneSemanticPlan,
        trace_context=TraceContext(
            output_dir=trace_dir / "repairs" / "rebuild_01",
            prompt_version=f"{prompt_version}.rebuild",
            prompt_fingerprint=sha256_json({"base": prompt_fingerprint, "errors": _error_details(current_error)}),
        ),
        domain_validator=validator,
        route_kind="rebuild",
    )
    _finalize_root_trace(trace_dir, invocation.value, repair_count=repair_count, rebuild_count=1)
    return invocation


def _raw_payload(trace_dir: Path) -> dict[str, Any] | None:
    path = trace_dir / "response.raw.json"
    if not path.is_file():
        return None
    raw = load_json(path)
    try:
        payload = json.loads(raw["content"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _root_request_fingerprint(trace_dir: Path) -> str:
    manifest = load_json(trace_dir / "manifest.json")
    return str(manifest["request_fingerprint"])


def _finalize_root_trace(
    trace_dir: Path,
    value: SceneSemanticPlan,
    *,
    repair_count: int,
    rebuild_count: int,
) -> None:
    trace = InvocationTrace(TraceContext(output_dir=trace_dir, prompt_version="scene_semantics.v1"))
    manifest = load_json(trace.manifest_path)
    write_json_atomic(trace.validated_path, value.model_dump(mode="json"))
    manifest.update(
        {
            "validation_status": "validated",
            "repair_count": repair_count,
            "rebuild_count": rebuild_count,
            "updated_at": utc_now(),
        }
    )
    manifest.pop("failure_type", None)
    manifest.pop("validation_errors", None)
    write_json_atomic(trace.manifest_path, manifest)


def _scene_text_for_path(payload: dict[str, Any], path: str, fallback: str) -> str:
    import re

    match = re.match(r"scenes\[(\d+)\]", path)
    if match:
        scenes = payload.get("scenes", [])
        index = int(match.group(1))
        if index < len(scenes) and isinstance(scenes[index], dict):
            return str(scenes[index].get("text") or fallback)
    return fallback


def _error_details(error: Exception) -> list[dict[str, Any]]:
    if isinstance(error, (AIDomainError, AISchemaError, AIJsonSyntaxError)):
        return error.details or [{"message": str(error)}]
    if isinstance(error, DomainValidationError):
        return [issue.model_dump(mode="json") for issue in error.issues]
    return [{"message": str(error)}]
