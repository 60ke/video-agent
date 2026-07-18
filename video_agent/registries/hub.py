from __future__ import annotations

import importlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import (
    AssetRoleRegistryDocument,
    CapabilityEntry,
    CategoryEntry,
    CategoryRegistryDocument,
    FrozenRegistryDocument,
    FrozenRegistrySnapshot,
    GroupTypeRegistryDocument,
    RegistryDocumentType,
)
from video_agent.io import sha256_json, write_json_atomic

from .loaders import load_registry_directory, parse_registry_document


_SPACE_RE = re.compile(r"\s+")


def normalize_registry_text(value: str) -> str:
    return _SPACE_RE.sub("", unicodedata.normalize("NFKC", value)).casefold()


class CapabilityRegistryHub:
    def __init__(self, documents: list[RegistryDocumentType]) -> None:
        self._documents: dict[str, RegistryDocumentType] = {}
        for document in documents:
            if document.registry_id in self._documents:
                raise ValueError(f"duplicate registry_id: {document.registry_id}")
            self._documents[document.registry_id] = document
        self._validate()

    @classmethod
    def load(cls, root: Path) -> "CapabilityRegistryHub":
        return cls(load_registry_directory(root))

    @classmethod
    def from_snapshot(cls, snapshot: FrozenRegistrySnapshot) -> "CapabilityRegistryHub":
        for frozen in snapshot.registries:
            if frozen.document.get("registry_id") != frozen.registry_id:
                raise ValueError(f"frozen registry ID mismatch: {frozen.registry_id}")
            if frozen.document.get("version") != frozen.version:
                raise ValueError(f"frozen registry version mismatch: {frozen.registry_id}")
            actual_hash = sha256_json(frozen.document)
            if actual_hash != frozen.content_sha256:
                raise ValueError(f"frozen registry content hash mismatch: {frozen.registry_id}")

        content_payload = [
            {
                "registry_id": item.registry_id,
                "version": item.version,
                "content_sha256": item.content_sha256,
            }
            for item in snapshot.registries
        ]
        actual_snapshot_hash = sha256_json(content_payload)
        if actual_snapshot_hash != snapshot.content_sha256:
            raise ValueError("frozen registry snapshot hash mismatch")
        if snapshot.snapshot_id != f"registry-snapshot://sha256/{actual_snapshot_hash}":
            raise ValueError("frozen registry snapshot ID mismatch")
        return cls([parse_registry_document(frozen.document) for frozen in snapshot.registries])

    @property
    def registry_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._documents))

    def registry(self, registry_id: str) -> RegistryDocumentType:
        try:
            return self._documents[registry_id]
        except KeyError as exc:
            raise KeyError(f"unknown registry: {registry_id}") from exc

    def entry(
        self,
        registry_id: str,
        entry_id: str,
        *,
        include_disabled: bool = False,
    ) -> CapabilityEntry | None:
        document = self.registry(registry_id)
        item = next((candidate for candidate in document.entries if candidate.id == entry_id), None)
        if item is None or (not include_disabled and not item.enabled):
            return None
        return item

    def require_entry(
        self,
        registry_id: str,
        entry_id: str,
        *,
        include_disabled: bool = False,
    ) -> CapabilityEntry:
        item = self.entry(registry_id, entry_id, include_disabled=include_disabled)
        if item is None:
            state = "enabled " if not include_disabled else ""
            raise KeyError(f"unknown {state}{registry_id} entry: {entry_id}")
        return item

    def resolve_category(self, text: str) -> CategoryEntry | None:
        document = self.registry("category")
        if not isinstance(document, CategoryRegistryDocument):
            raise TypeError("category registry has an invalid document type")
        needle = normalize_registry_text(text)
        for category in document.entries:
            if not category.enabled:
                continue
            candidates = [category.id, category.display_name, *category.aliases]
            if any(normalize_registry_text(candidate) == needle for candidate in candidates):
                return category
        return None

    def snapshot(self) -> FrozenRegistrySnapshot:
        registries: list[FrozenRegistryDocument] = []
        for registry_id in sorted(self._documents):
            document = self._documents[registry_id]
            payload = document.model_dump(mode="json", exclude_none=True)
            registries.append(
                FrozenRegistryDocument(
                    registry_id=registry_id,
                    version=document.version,
                    content_sha256=sha256_json(payload),
                    document=payload,
                )
            )
        content_payload = [
            {
                "registry_id": item.registry_id,
                "version": item.version,
                "content_sha256": item.content_sha256,
            }
            for item in registries
        ]
        content_sha256 = sha256_json(content_payload)
        return FrozenRegistrySnapshot(
            snapshot_id=f"registry-snapshot://sha256/{content_sha256}",
            created_at=datetime.now(timezone.utc),
            content_sha256=content_sha256,
            registries=registries,
        )

    def freeze(self, output_path: Path) -> FrozenRegistrySnapshot:
        snapshot = self.snapshot()
        write_json_atomic(output_path, snapshot)
        return snapshot

    def _validate(self) -> None:
        for registry_id, document in self._documents.items():
            ids = [entry.id for entry in document.entries]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate entry ID in {registry_id}")
            for entry in document.entries:
                if entry.handler is not None:
                    self._validate_handler(registry_id, entry)
        self._validate_category_aliases()
        self._validate_cross_references()

    @staticmethod
    def _validate_handler(registry_id: str, entry: CapabilityEntry) -> None:
        module_name, separator, attribute_name = entry.handler.partition(":")
        if not separator or not module_name or not attribute_name:
            raise ValueError(f"invalid handler for {registry_id}/{entry.id}: {entry.handler}")
        try:
            module = importlib.import_module(module_name)
            handler: Any = module
            for part in attribute_name.split("."):
                handler = getattr(handler, part)
        except (ImportError, AttributeError) as exc:
            raise ValueError(f"handler not found for {registry_id}/{entry.id}: {entry.handler}") from exc
        if not callable(handler):
            raise ValueError(f"handler is not callable for {registry_id}/{entry.id}: {entry.handler}")

    def _validate_category_aliases(self) -> None:
        document = self._documents.get("category")
        if document is None:
            raise ValueError("required registry is missing: category")
        if not isinstance(document, CategoryRegistryDocument):
            raise TypeError("category registry has an invalid document type")
        owners: dict[str, str] = {}
        for category in document.entries:
            if not category.enabled:
                continue
            normalized_aliases = [normalize_registry_text(alias) for alias in category.aliases]
            if len(normalized_aliases) != len(set(normalized_aliases)):
                raise ValueError(f"duplicate category aliases after normalization: {category.id}")
            for value in [category.id, category.display_name, *category.aliases]:
                normalized = normalize_registry_text(value)
                owner = owners.setdefault(normalized, category.id)
                if owner != category.id:
                    raise ValueError(
                        f"category alias collision after normalization: {value!r} -> {owner}, {category.id}"
                    )

    def _validate_cross_references(self) -> None:
        required = {
            "asset_role",
            "visual_structure",
            "operation_intent",
            "claim",
            "group_type",
            "configured_asset",
        }
        missing = sorted(required - self._documents.keys())
        if missing:
            raise ValueError(f"required registries are missing: {missing}")

        roles = self.registry("asset_role")
        groups = self.registry("group_type")
        if not isinstance(roles, AssetRoleRegistryDocument):
            raise TypeError("asset_role registry has an invalid document type")
        if not isinstance(groups, GroupTypeRegistryDocument):
            raise TypeError("group_type registry has an invalid document type")

        role_ids = {entry.id for entry in roles.entries}
        group_ids = {entry.id for entry in groups.entries}
        structure_ids = {entry.id for entry in self.registry("visual_structure").entries}
        derivation_ids = (
            {entry.id for entry in self.registry("derivation").entries}
            if "derivation" in self._documents
            else set()
        )
        for role in roles.entries:
            self._require_known(role.allowed_parent_roles, role_ids, f"asset_role/{role.id}.allowed_parent_roles")
            self._require_known(role.allowed_group_types, group_ids, f"asset_role/{role.id}.allowed_group_types")
            self._require_known(
                role.display_capability_tags,
                structure_ids,
                f"asset_role/{role.id}.display_capability_tags",
            )
            if derivation_ids:
                self._require_known(
                    role.allowed_derivation_ids,
                    derivation_ids,
                    f"asset_role/{role.id}.allowed_derivation_ids",
                )
        for group in groups.entries:
            self._require_known(group.allowed_member_roles, role_ids, f"group_type/{group.id}.allowed_member_roles")

    @staticmethod
    def _require_known(values: list[str], known: set[str], path: str) -> None:
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown cross-registry references at {path}: {unknown}")
