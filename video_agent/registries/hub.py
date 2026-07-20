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
    DerivationEntry,
    DerivationRegistryDocument,
    EffectEntry,
    EffectRegistryDocument,
    FrozenRegistryDocument,
    FrozenRegistrySnapshot,
    GroupTypeRegistryDocument,
    RelationPatternRegistryDocument,
    RegistryDocumentType,
    SfxEntry,
    SfxProfileRegistryDocument,
    SfxRegistryDocument,
    VoiceRegistryDocument,
)
from video_agent.io import sha256_file, sha256_json, write_json_atomic

from .loaders import load_registry_directory, parse_registry_document


_SPACE_RE = re.compile(r"\s+")
_STAGE5_REQUIRED = frozenset({"derivation", "effect", "sfx", "sfx_profile", "voice"})


def normalize_registry_text(value: str) -> str:
    return _SPACE_RE.sub("", unicodedata.normalize("NFKC", value)).casefold()


class CapabilityRegistryHub:
    def __init__(
        self,
        documents: list[RegistryDocumentType],
        *,
        project_root: Path | None = None,
        require_stage5: bool = False,
    ) -> None:
        self._documents: dict[str, RegistryDocumentType] = {}
        self._project_root = project_root
        self._require_stage5 = require_stage5
        for document in documents:
            if document.registry_id in self._documents:
                raise ValueError(f"duplicate registry_id: {document.registry_id}")
            self._documents[document.registry_id] = document
        self._validate()

    @classmethod
    def load(cls, root: Path) -> "CapabilityRegistryHub":
        root = root.resolve()
        return cls(
            load_registry_directory(root),
            project_root=root.parents[2],
            require_stage5=True,
        )

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
            "relation_pattern",
            "configured_asset",
        }
        if self._require_stage5:
            required |= set(_STAGE5_REQUIRED)
        missing = sorted(required - self._documents.keys())
        if missing:
            raise ValueError(f"required registries are missing: {missing}")

        roles = self.registry("asset_role")
        groups = self.registry("group_type")
        if not isinstance(roles, AssetRoleRegistryDocument):
            raise TypeError("asset_role registry has an invalid document type")
        if not isinstance(groups, GroupTypeRegistryDocument):
            raise TypeError("group_type registry has an invalid document type")
        patterns = self.registry("relation_pattern")
        if not isinstance(patterns, RelationPatternRegistryDocument):
            raise TypeError("relation_pattern registry has an invalid document type")

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
        group_by_id = {entry.id: entry for entry in groups.entries}
        for pattern in patterns.entries:
            self._require_known([pattern.group_type], group_ids, f"relation_pattern/{pattern.id}.group_type")
            self._require_known(
                [member.asset_role for member in pattern.members],
                role_ids,
                f"relation_pattern/{pattern.id}.members.asset_role",
            )
            group = group_by_id.get(pattern.group_type)
            if group is not None:
                disallowed = sorted(
                    {
                        member.asset_role
                        for member in pattern.members
                        if member.asset_role not in group.allowed_member_roles
                    }
                )
                if disallowed:
                    raise ValueError(
                        f"relation pattern roles are not allowed by group type {pattern.group_type}: "
                        f"{pattern.id} -> {disallowed}"
                    )
        for configured in self.registry("configured_asset").entries:
            allowed_roles = configured.capabilities.get("allowed_asset_roles")
            if not isinstance(allowed_roles, list) or not allowed_roles:
                raise ValueError(
                    f"configured_asset/{configured.id}.capabilities.allowed_asset_roles must be a non-empty list"
                )
            self._require_known(
                [str(role) for role in allowed_roles],
                role_ids,
                f"configured_asset/{configured.id}.capabilities.allowed_asset_roles",
            )
        self._validate_stage5_registries(role_ids=role_ids, structure_ids=structure_ids)

    def _validate_stage5_registries(self, *, role_ids: set[str], structure_ids: set[str]) -> None:
        pattern_ids = {entry.id for entry in self.registry("relation_pattern").entries}
        if "derivation" in self._documents:
            document = self.registry("derivation")
            if not isinstance(document, DerivationRegistryDocument):
                raise TypeError("derivation registry has an invalid document type")
            for entry in document.entries:
                if not isinstance(entry, DerivationEntry):
                    raise TypeError(f"derivation/{entry.id} has an invalid entry type")
                caps = entry.capabilities
                self._require_known(caps.input_roles, role_ids, f"derivation/{entry.id}.input_roles")
                self._require_known(caps.context_roles, role_ids, f"derivation/{entry.id}.context_roles")
                self._require_known(caps.output_roles, role_ids, f"derivation/{entry.id}.output_roles")
                self._require_known(
                    caps.allowed_group_patterns,
                    pattern_ids,
                    f"derivation/{entry.id}.allowed_group_patterns",
                )

        if "effect" in self._documents:
            document = self.registry("effect")
            if not isinstance(document, EffectRegistryDocument):
                raise TypeError("effect registry has an invalid document type")
            effect_ids = {entry.id for entry in document.entries}
            for entry in document.entries:
                if not isinstance(entry, EffectEntry):
                    raise TypeError(f"effect/{entry.id} has an invalid entry type")
                caps = entry.capabilities
                self._require_known(caps.visual_structures, structure_ids, f"effect/{entry.id}.visual_structures")
                self._require_known(caps.asset_roles, role_ids, f"effect/{entry.id}.asset_roles")
                self._require_known(
                    caps.fallback_effect_ids,
                    effect_ids,
                    f"effect/{entry.id}.fallback_effect_ids",
                )
                binding_set = set(caps.event_bindings)
                timing_keys = set(caps.event_timing)
                if binding_set != timing_keys:
                    raise ValueError(
                        f"effect/{entry.id}.event_timing keys must match event_bindings exactly"
                    )
                if caps.event_timing:
                    shortest = min(
                        variant.minimum_interval_frames
                        for timing in caps.event_timing.values()
                        for variant in timing.variants
                    )
                    if caps.minimum_scene_frames > shortest:
                        raise ValueError(
                            f"effect/{entry.id}.minimum_scene_frames exceeds shortest variant"
                        )

        if "sfx" in self._documents:
            document = self.registry("sfx")
            if not isinstance(document, SfxRegistryDocument):
                raise TypeError("sfx registry has an invalid document type")
            sfx_ids = {entry.id for entry in document.entries}
            for entry in document.entries:
                if not isinstance(entry, SfxEntry):
                    raise TypeError(f"sfx/{entry.id} has an invalid entry type")
                self._require_known(
                    entry.capabilities.alternate_sfx_ids,
                    sfx_ids,
                    f"sfx/{entry.id}.alternate_sfx_ids",
                )
                self._validate_sfx_asset_file(entry)

        if "sfx_profile" in self._documents:
            document = self.registry("sfx_profile")
            if not isinstance(document, SfxProfileRegistryDocument):
                raise TypeError("sfx_profile registry has an invalid document type")

        if "voice" in self._documents:
            document = self.registry("voice")
            if not isinstance(document, VoiceRegistryDocument):
                raise TypeError("voice registry has an invalid document type")

    def _validate_sfx_asset_file(self, entry: SfxEntry) -> None:
        if self._project_root is None:
            return
        audio_path = self._project_root / entry.capabilities.relative_path
        if not audio_path.is_file():
            raise ValueError(f"sfx/{entry.id} audio file missing: {entry.capabilities.relative_path}")
        actual = sha256_file(audio_path)
        if actual != entry.capabilities.content_sha256:
            raise ValueError(f"sfx/{entry.id} content hash mismatch: {entry.capabilities.relative_path}")
        if (
            entry.capabilities.sample_rate != 48_000
            or entry.capabilities.sample_width_bits != 16
            or entry.capabilities.channels != 2
        ):
            raise ValueError(f"sfx/{entry.id} must declare 48kHz/16-bit/stereo")

    @staticmethod
    def _require_known(values: list[str], known: set[str], path: str) -> None:
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown cross-registry references at {path}: {unknown}")
