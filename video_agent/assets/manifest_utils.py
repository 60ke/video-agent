from __future__ import annotations

from typing import Any


LEGACY_REVIEW_FIELDS = frozenset(
    {
        "quality_status",
        "quality_checks",
        "human_reviewed",
        "reviewed_at",
        "reviewed_by",
        "review_preview_path",
        "callout_base_path",
        "callout_base_sha256",
        "callout_layer_path",
        "callout_layer_sha256",
        "callout_component_area",
        "callout_layer_method",
    }
)


def without_legacy_review_fields(value: Any) -> Any:
    """Return a manifest payload without obsolete review or callout metadata."""
    if isinstance(value, dict):
        return {
            key: without_legacy_review_fields(item)
            for key, item in value.items()
            if key not in LEGACY_REVIEW_FIELDS
        }
    if isinstance(value, list):
        return [without_legacy_review_fields(item) for item in value]
    return value
