from __future__ import annotations

import json
import re
from typing import Iterable

from video_agent.contracts.v4 import AssetRecord, OperationEvent, SemanticScene


# Closed vocabulary of spoken parameter labels used by Stage0/Stage4 callouts.
# Not a free-form NLP extractor — only these tokens can enter callout_fields.
_KNOWN_OPERATION_FIELDS: tuple[str, ...] = (
    "行业",
    "风格",
    "尺寸",
    "比例",
    "材质",
    "颜色",
    "文案",
    "主题",
    "场景",
    "构图",
)


def extract_spoken_operation_fields(
    scene_text: str,
    events: Iterable[OperationEvent] | None = None,
) -> list[str]:
    haystack = scene_text
    for event in events or ():
        haystack += event.phrase
    found: list[str] = []
    for label in _KNOWN_OPERATION_FIELDS:
        if label in haystack and label not in found:
            found.append(label)
    return found


def extract_registered_required_fields(parent: AssetRecord | None) -> list[str]:
    """Read page-registered fields from asset description; never invent from narration."""
    if parent is None or not parent.description:
        return []
    text = parent.description.strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            raw = payload.get("registered_required_fields") or payload.get("required_fields")
            if isinstance(raw, list):
                return [str(item) for item in raw if str(item).strip()]
    match = re.search(r"registered_required_fields\s*[:=]\s*(.+)$", text, flags=re.IGNORECASE)
    if match:
        return [part.strip() for part in re.split(r"[,，、]", match.group(1)) if part.strip()]
    return []


def resolve_callout_fields(
    *,
    spoken_operation_fields: list[str],
    registered_required_fields: list[str],
) -> list[str]:
    if not registered_required_fields:
        # Without registered page fields, Stage4 cannot invent callouts from speech alone.
        return []
    registered = set(registered_required_fields)
    return [field for field in spoken_operation_fields if field in registered]


def parameter_narrative_fields(
    scene: SemanticScene,
    parent: AssetRecord | None,
) -> tuple[list[str], list[str], list[str]]:
    spoken = extract_spoken_operation_fields(scene.text, scene.events)
    registered = extract_registered_required_fields(parent)
    callouts = resolve_callout_fields(
        spoken_operation_fields=spoken,
        registered_required_fields=registered,
    )
    return spoken, registered, callouts
