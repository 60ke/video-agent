from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import (
    AssetRoleRegistryDocument,
    CategoryRegistryDocument,
    ClaimRegistryDocument,
    GroupTypeRegistryDocument,
    RegistryDocument,
    RegistryDocumentType,
)
from video_agent.io import load_json


_TYPED_DOCUMENTS = {
    "category": CategoryRegistryDocument,
    "asset_role": AssetRoleRegistryDocument,
    "claim": ClaimRegistryDocument,
    "group_type": GroupTypeRegistryDocument,
}


def parse_registry_document(payload: dict[str, Any]) -> RegistryDocumentType:
    """Parse registry configuration with strict JSON semantics.

    V4 contracts are strict at Python boundaries. Registry files are JSON,
    where enum values are represented by strings, so they must enter Pydantic
    through ``model_validate_json`` instead of strict ``model_validate``.
    """

    registry_id = payload.get("registry_id")
    if not isinstance(registry_id, str) or not registry_id:
        raise ValueError("registry document has no registry_id")
    model = _TYPED_DOCUMENTS.get(registry_id, RegistryDocument)
    return model.model_validate_json(json.dumps(payload, ensure_ascii=False))


def load_registry_document(path: Path) -> RegistryDocumentType:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"registry document must be an object: {path}")
    try:
        return parse_registry_document(payload)
    except ValueError as exc:
        raise ValueError(f"invalid registry document {path}: {exc}") from exc


def load_registry_directory(root: Path) -> list[RegistryDocumentType]:
    if not root.is_dir():
        raise FileNotFoundError(f"registry directory not found: {root}")
    paths = sorted(root.glob("*.json"), key=lambda item: item.name.casefold())
    if not paths:
        raise FileNotFoundError(f"registry directory contains no JSON documents: {root}")
    return [load_registry_document(path) for path in paths]
