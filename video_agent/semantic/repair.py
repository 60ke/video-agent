from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from video_agent.ai_runtime import AsyncModelGateway, TraceContext
from video_agent.contracts.v4 import FieldRepairPatch
from video_agent.contracts.v4.common import ValidationIssue
from video_agent.registries import CapabilityRegistrySnapshot

from .prompts import load_field_repair_prompt


REPAIRABLE_CODES = {
    "unknown_or_disabled_registry_id",
    "unknown_or_disabled_category",
    "unknown_slot",
    "unknown_scene_input",
    "unknown_scene_output",
    "group_type_mismatch",
    "unknown_group_alias",
}
_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def can_field_repair(issue: ValidationIssue) -> bool:
    return issue.code in REPAIRABLE_CODES and _path_exists_for_replace(issue.path)


async def request_field_repair(
    *,
    gateway: AsyncModelGateway,
    repo_root: Path,
    invalid_payload: dict[str, Any],
    issue: ValidationIssue,
    registry: CapabilityRegistrySnapshot,
    original_text: str,
    trace_dir: Path,
) -> dict[str, Any]:
    prompt = load_field_repair_prompt(repo_root)
    pointer = field_path_to_pointer(issue.path)
    invalid_value = get_path_value(invalid_payload, issue.path)
    allowed_values = allowed_values_for_path(issue.path, invalid_payload, registry)
    invocation = await gateway.invoke_structured(
        capability="field_repair",
        system_prompt=prompt.system_prompt,
        input_payload={
            "contract": "SceneSemanticPlan/v4.1",
            "field_path": issue.path,
            "invalid_value": invalid_value,
            "validation_code": issue.code,
            "allowed_values": allowed_values,
            "local_context": local_context(invalid_payload, issue.path),
            "original_text": original_text,
        },
        output_type=FieldRepairPatch,
        trace_context=TraceContext(
            output_dir=trace_dir,
            prompt_version=prompt.version,
            prompt_fingerprint=prompt.fingerprint,
        ),
    )
    patch = invocation.value
    if patch.path != pointer:
        raise ValueError(f"field repair attempted a different path: expected={pointer}, actual={patch.path}")
    if allowed_values and patch.value not in allowed_values:
        raise ValueError(f"field repair value is outside allowed values: {patch.value}")
    return apply_replace(invalid_payload, issue.path, patch.value)


def field_path_to_pointer(path: str) -> str:
    parts = _path_parts(path)
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def get_path_value(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in _path_parts(path):
        value = value[part]
    return value


def apply_replace(payload: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    parts = _path_parts(path)
    parent: Any = result
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = value
    return result


def allowed_values_for_path(
    path: str,
    payload: dict[str, Any],
    registry: CapabilityRegistrySnapshot,
) -> list[Any]:
    if path.endswith("category_id"):
        return [item.category_id for item in registry.categories if item.enabled]
    mapping = {
        "asset_role": "asset_roles",
        "visual_structure": "visual_structures",
        "intent": "operation_intents",
        "claim_id": "claims",
        "group_type": "group_types",
        "config_key": "configured_assets",
    }
    for suffix, registry_name in mapping.items():
        if path.endswith(suffix):
            return [item.item_id for item in getattr(registry, registry_name) if item.enabled]
    scene = local_context(payload, path)
    if path.endswith("target_slot") or path.endswith("bound_slot") or "supporting_slots" in path:
        return [item["slot_id"] for item in scene.get("slots", [])]
    if path.endswith("input_name"):
        return [item["input_name"] for item in scene.get("inputs", [])]
    return []


def local_context(payload: dict[str, Any], path: str) -> dict[str, Any]:
    parts = _path_parts(path)
    if len(parts) >= 2 and parts[0] == "scenes" and isinstance(parts[1], int):
        return copy.deepcopy(payload["scenes"][parts[1]])
    return {}


def _path_exists_for_replace(path: str) -> bool:
    return bool(path and not path.endswith(".supporting_slots"))


def _path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for match in _TOKEN_RE.finditer(path):
        field, index = match.groups()
        parts.append(int(index) if index is not None else field)
    if not parts:
        raise ValueError(f"invalid field path: {json.dumps(path)}")
    return parts
