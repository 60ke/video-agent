from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from video_agent.assets.v4_validation import validate_asset_against_registry, validate_group_against_assets
from video_agent.contracts.v4 import (
    AssetGroup,
    AssetGroupMember,
    AssetLineage,
    AssetRecord,
    AssetRepositorySnapshot,
    AssetRepositorySnapshotAsset,
    AssetRepositorySnapshotGroup,
    AssetStatus,
    EvidenceClass,
    Orientation,
    SourceKind,
)
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistryHub

from .object_store import AssetObjectStore
from .repository import (
    AssetConflictError,
    AssetDraft,
    AssetGroupDraft,
    AssetNotFoundError,
    AssetQuery,
    GroupQuery,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repository_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS id_sequences (entity_type TEXT PRIMARY KEY CHECK(entity_type IN ('asset','group')), next_value INTEGER NOT NULL CHECK(next_value >= 1));
CREATE TABLE IF NOT EXISTS assets (
 asset_ref TEXT PRIMARY KEY, filename TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, content_sha256 TEXT NOT NULL,
 media_type TEXT NOT NULL, module TEXT, category_id TEXT, category_path_json TEXT NOT NULL, asset_role TEXT NOT NULL,
 case_label TEXT, industry TEXT, description TEXT, width INTEGER NOT NULL, height INTEGER NOT NULL, orientation TEXT NOT NULL,
 animated INTEGER NOT NULL, source_kind TEXT NOT NULL, origin_type TEXT NOT NULL, evidence_class TEXT NOT NULL,
 claims_json TEXT NOT NULL, status TEXT NOT NULL, superseded_by TEXT REFERENCES assets(asset_ref), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS asset_lineage (
 asset_ref TEXT PRIMARY KEY REFERENCES assets(asset_ref), derivation_type TEXT NOT NULL, executor_id TEXT NOT NULL,
 provider TEXT, model TEXT, prompt_template_version TEXT, prompt_sha256 TEXT, parameters_sha256 TEXT NOT NULL,
 derivation_signature TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS asset_parents (
 asset_ref TEXT NOT NULL REFERENCES assets(asset_ref), parent_asset_ref TEXT NOT NULL REFERENCES assets(asset_ref),
 parent_order INTEGER NOT NULL, PRIMARY KEY(asset_ref,parent_asset_ref), UNIQUE(asset_ref,parent_order));
CREATE TABLE IF NOT EXISTS asset_groups (
 group_ref TEXT PRIMARY KEY, group_type TEXT NOT NULL, pattern_id TEXT NOT NULL, category_id TEXT NOT NULL,
 status TEXT NOT NULL, superseded_by TEXT REFERENCES asset_groups(group_ref), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS asset_group_members (
 group_ref TEXT NOT NULL REFERENCES asset_groups(group_ref), member_key TEXT NOT NULL, asset_role TEXT NOT NULL,
 asset_ref TEXT NOT NULL REFERENCES assets(asset_ref), member_order INTEGER NOT NULL,
 PRIMARY KEY(group_ref,member_key), UNIQUE(group_ref,member_order));
CREATE INDEX IF NOT EXISTS idx_assets_active_role_category_orientation ON assets(status,asset_role,category_id,orientation);
CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_lineage_derivation_signature ON asset_lineage(derivation_signature);
CREATE INDEX IF NOT EXISTS idx_asset_groups_active_pattern_category ON asset_groups(status,pattern_id,category_id);
CREATE INDEX IF NOT EXISTS idx_asset_group_members_asset ON asset_group_members(asset_ref);
CREATE TABLE IF NOT EXISTS configured_asset_bindings (
 config_key TEXT PRIMARY KEY, asset_ref TEXT NOT NULL REFERENCES assets(asset_ref), updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS legacy_id_map (
 source_name TEXT NOT NULL, legacy_id TEXT NOT NULL, entity_kind TEXT NOT NULL CHECK(entity_kind IN ('asset','group')),
 v4_ref TEXT NOT NULL, source_payload_json TEXT NOT NULL, PRIMARY KEY(source_name,legacy_id));
CREATE TABLE IF NOT EXISTS migration_runs (
 migration_key TEXT PRIMARY KEY, mapping_version TEXT NOT NULL, input_fingerprint TEXT NOT NULL, status TEXT NOT NULL,
 report_json TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT);
"""


class SQLiteAssetRepository:
    def __init__(self, db_path: Path, object_store: AssetObjectStore, registry: CapabilityRegistryHub) -> None:
        self.db_path, self.object_store, self.registry = db_path, object_store, registry
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.executescript(_SCHEMA)
        with self.transaction():
            self.connection.execute("INSERT OR IGNORE INTO id_sequences VALUES ('asset',1)")
            self.connection.execute("INSERT OR IGNORE INTO id_sequences VALUES ('group',1)")
            value = self.connection.execute("SELECT value FROM repository_meta WHERE key='schema_version'").fetchone()
            if value is None:
                self.connection.execute("INSERT INTO repository_meta VALUES ('schema_version',?)", (str(SCHEMA_VERSION),))
            elif value["value"] != str(SCHEMA_VERSION):
                raise AssetConflictError(f"unsupported repository schema version: {value['value']}")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def get_asset(self, asset_ref: str, *, include_superseded: bool = True) -> AssetRecord | None:
        row = self.connection.execute("SELECT * FROM assets WHERE asset_ref=?", (asset_ref,)).fetchone()
        if row is None or (not include_superseded and row["status"] != AssetStatus.ACTIVE.value):
            return None
        return self._asset_from_row(row)

    def query_assets(self, query: AssetQuery) -> list[AssetRecord]:
        clauses, values = [], []
        for column, items in (
            ("category_id", query.category_ids),
            ("asset_role", query.asset_roles),
            ("source_kind", query.source_kinds),
            ("orientation", query.orientations),
        ):
            if items:
                clauses.append(f"a.{column} IN ({','.join('?' for _ in items)})")
                values.extend(item.value if hasattr(item, "value") else item for item in items)
        if query.active_only:
            clauses.append("a.status='active'")
            clauses.append(
                "NOT EXISTS (WITH RECURSIVE ancestors(ref) AS (SELECT parent_asset_ref FROM asset_parents WHERE asset_ref=a.asset_ref UNION ALL SELECT p.parent_asset_ref FROM asset_parents p JOIN ancestors x ON p.asset_ref=x.ref) SELECT 1 FROM ancestors JOIN assets parent ON parent.asset_ref=ancestors.ref WHERE parent.status='superseded')"
            )
        for claim in query.claims:
            clauses.append("EXISTS (SELECT 1 FROM json_each(a.claims_json) WHERE value=?)")
            values.append(claim)
        sql = "SELECT a.* FROM assets a" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY a.asset_ref"
        return [self._asset_from_row(row) for row in self.connection.execute(sql, values)]

    def register_asset(self, draft: AssetDraft) -> AssetRecord:
        with self.transaction():
            return self._register_asset(draft)

    def _register_asset(self, draft: AssetDraft) -> AssetRecord:
        self.object_store.verify(draft.object_key, draft.content_sha256)
        ref = self._allocate("asset")
        now = datetime.now(timezone.utc)
        lineage = draft.lineage
        if lineage is not None:
            for parent in lineage.parent_asset_refs:
                if self.get_asset(parent) is None:
                    raise AssetNotFoundError(f"parent asset not found: {parent}")
        asset = AssetRecord(asset_ref=ref, created_at=now, status=AssetStatus.ACTIVE, superseded_by=None, **draft.__dict__)
        validate_asset_against_registry(asset, self.registry)
        self.connection.execute(
            """INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref,
                asset.filename,
                asset.object_key,
                asset.content_sha256,
                asset.media_type,
                asset.module,
                asset.category_id,
                json.dumps(asset.category_path, ensure_ascii=False),
                asset.asset_role,
                asset.case_label,
                asset.industry,
                asset.description,
                asset.width,
                asset.height,
                asset.orientation.value,
                int(asset.animated),
                asset.source_kind.value,
                asset.origin_type,
                asset.evidence_class.value,
                json.dumps(asset.claims, ensure_ascii=False),
                asset.status.value,
                None,
                now.isoformat(),
            ),
        )
        if lineage:
            self.connection.execute(
                "INSERT INTO asset_lineage VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    ref,
                    lineage.derivation_type,
                    lineage.executor_id,
                    lineage.provider,
                    lineage.model,
                    lineage.prompt_template_version,
                    lineage.prompt_sha256,
                    lineage.parameters_sha256,
                    lineage.derivation_signature,
                    lineage.created_at.isoformat(),
                ),
            )
            self.connection.executemany(
                "INSERT INTO asset_parents VALUES (?,?,?)",
                [(ref, parent, index) for index, parent in enumerate(lineage.parent_asset_refs, 1)],
            )
        return asset

    def supersede_asset(self, old_ref: str, replacement: AssetDraft) -> AssetRecord:
        with self.transaction():
            old = self.get_asset(old_ref)
            if old is None:
                raise AssetNotFoundError(old_ref)
            if old.status != AssetStatus.ACTIVE:
                raise AssetConflictError(f"asset is not active: {old_ref}")
            new = self._register_asset(replacement)
            self.connection.execute("UPDATE assets SET status='superseded', superseded_by=? WHERE asset_ref=?", (new.asset_ref, old_ref))
            return new

    def find_by_derivation_signature(self, signature: str) -> AssetRecord | None:
        row = self.connection.execute(
            "SELECT a.* FROM assets a JOIN asset_lineage l ON l.asset_ref=a.asset_ref WHERE l.derivation_signature=?", (signature,)
        ).fetchone()
        return self._asset_from_row(row) if row else None

    def get_group(self, group_ref: str, *, include_superseded: bool = True) -> AssetGroup | None:
        row = self.connection.execute("SELECT * FROM asset_groups WHERE group_ref=?", (group_ref,)).fetchone()
        if row is None or (not include_superseded and row["status"] != AssetStatus.ACTIVE.value):
            return None
        return self._group_from_row(row)

    def query_groups(self, query: GroupQuery) -> list[AssetGroup]:
        clauses, values = [], []
        for column, items in (("group_type", query.group_types), ("pattern_id", query.pattern_ids), ("category_id", query.category_ids)):
            if items:
                clauses.append(f"g.{column} IN ({','.join('?' for _ in items)})")
                values.extend(items)
        if query.member_roles:
            clauses.append(
                f"EXISTS (SELECT 1 FROM asset_group_members m WHERE m.group_ref=g.group_ref "
                f"AND m.asset_role IN ({','.join('?' for _ in query.member_roles)}))"
            )
            values.extend(query.member_roles)
        if query.active_only:
            clauses.append("g.status='active'")
        sql = "SELECT g.* FROM asset_groups g" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY g.group_ref"
        return [self._group_from_row(row) for row in self.connection.execute(sql, values)]

    def register_group(self, draft: AssetGroupDraft) -> AssetGroup:
        with self.transaction():
            return self._register_group(draft)

    def _register_group(self, draft: AssetGroupDraft) -> AssetGroup:
        ref, now = self._allocate("group"), datetime.now(timezone.utc)
        group = AssetGroup(group_ref=ref, status=AssetStatus.ACTIVE, superseded_by=None, created_at=now, **draft.__dict__)
        assets = {member.asset_ref: self.get_asset(member.asset_ref) for member in group.members}
        validate_group_against_assets(group, {ref: asset for ref, asset in assets.items() if asset is not None}, self.registry)
        self.connection.execute(
            "INSERT INTO asset_groups VALUES (?,?,?,?,?,?,?)",
            (ref, group.group_type, group.pattern_id, group.category_id, "active", None, now.isoformat()),
        )
        self.connection.executemany(
            "INSERT INTO asset_group_members VALUES (?,?,?,?,?)",
            [(ref, member.member_key, member.asset_role, member.asset_ref, member.order) for member in group.members],
        )
        return group

    def supersede_group(self, old_ref: str, replacement: AssetGroupDraft) -> AssetGroup:
        with self.transaction():
            old = self.get_group(old_ref)
            if old is None:
                raise AssetNotFoundError(old_ref)
            if old.status != AssetStatus.ACTIVE:
                raise AssetConflictError(f"group is not active: {old_ref}")
            new = self._register_group(replacement)
            self.connection.execute(
                "UPDATE asset_groups SET status='superseded', superseded_by=? WHERE group_ref=?", (new.group_ref, old_ref)
            )
            return new

    def bind_configured_asset(self, config_key: str, asset_ref: str) -> None:
        with self.transaction():
            self.validate_configured_asset_binding(config_key, asset_ref)
            self.connection.execute(
                "INSERT INTO configured_asset_bindings VALUES (?,?,?) ON CONFLICT(config_key) DO UPDATE SET asset_ref=excluded.asset_ref,updated_at=excluded.updated_at",
                (config_key, asset_ref, datetime.now(timezone.utc).isoformat()),
            )

    def validate_configured_asset_binding(self, config_key: str, asset_ref: str) -> AssetRecord:
        configured = self.registry.entry("configured_asset", config_key)
        if configured is None:
            raise AssetConflictError(f"unknown configured asset: {config_key}")
        asset = self.get_asset(asset_ref, include_superseded=False)
        if asset is None:
            raise AssetNotFoundError(asset_ref)
        allowed_roles = configured.capabilities.get("allowed_asset_roles", [])
        if asset.asset_role not in allowed_roles:
            raise AssetConflictError(
                f"configured asset {config_key} requires one of {allowed_roles}, got {asset.asset_role}"
            )
        return asset

    def configured_asset(self, config_key: str) -> AssetRecord | None:
        row = self.connection.execute("SELECT asset_ref FROM configured_asset_bindings WHERE config_key=?", (config_key,)).fetchone()
        return self.get_asset(row["asset_ref"], include_superseded=False) if row else None

    def freeze(self, asset_refs: list[str], group_refs: list[str]) -> AssetRepositorySnapshot:
        assets = [self.get_asset(ref) for ref in sorted(set(asset_refs))]
        groups = [self.get_group(ref) for ref in sorted(set(group_refs))]
        if None in assets or None in groups:
            raise AssetNotFoundError("cannot freeze missing repository record")
        snapshot_assets = []
        for asset in assets:
            assert asset is not None
            self.object_store.verify(asset.object_key, asset.content_sha256)
            lineage_hash = sha256_json(asset.lineage) if asset.lineage else None
            snapshot_assets.append(
                AssetRepositorySnapshotAsset(
                    asset_ref=asset.asset_ref,
                    object_key=asset.object_key,
                    content_sha256=asset.content_sha256,
                    status=asset.status,
                    lineage_sha256=lineage_hash,
                )
            )
        snapshot_groups = [
            AssetRepositorySnapshotGroup(group_ref=group.group_ref, content_sha256=sha256_json(group)) for group in groups if group
        ]
        digest = self._snapshot_digest(snapshot_assets, snapshot_groups)
        return AssetRepositorySnapshot(
            snapshot_id=f"asset-snapshot://sha256/{digest}",
            created_at=datetime.now(timezone.utc),
            repository_schema_version=SCHEMA_VERSION,
            content_sha256=digest,
            assets=snapshot_assets,
            groups=snapshot_groups,
        )

    def validate_snapshot(self, snapshot: AssetRepositorySnapshot) -> None:
        if snapshot.repository_schema_version != SCHEMA_VERSION:
            raise AssetConflictError(
                f"unsupported snapshot schema version: {snapshot.repository_schema_version}"
            )
        digest = self._snapshot_digest(snapshot.assets, snapshot.groups)
        if digest != snapshot.content_sha256:
            raise AssetConflictError("snapshot content hash mismatch")
        if snapshot.snapshot_id != f"asset-snapshot://sha256/{digest}":
            raise AssetConflictError("snapshot id does not match content hash")
        for summary in snapshot.assets:
            asset = self.get_asset(summary.asset_ref, include_superseded=True)
            if asset is None:
                raise AssetNotFoundError(summary.asset_ref)
            lineage_hash = sha256_json(asset.lineage) if asset.lineage else None
            if (
                asset.object_key != summary.object_key
                or asset.content_sha256 != summary.content_sha256
                or asset.status != summary.status
                or lineage_hash != summary.lineage_sha256
            ):
                raise AssetConflictError(f"snapshot asset drift: {summary.asset_ref}")
            self.object_store.verify(asset.object_key, asset.content_sha256)
        for summary in snapshot.groups:
            group = self.get_group(summary.group_ref, include_superseded=True)
            if group is None:
                raise AssetNotFoundError(summary.group_ref)
            if sha256_json(group) != summary.content_sha256:
                raise AssetConflictError(f"snapshot group drift: {summary.group_ref}")

    def restore_snapshot(self, snapshot: AssetRepositorySnapshot) -> tuple[list[AssetRecord], list[AssetGroup]]:
        self.validate_snapshot(snapshot)
        assets: list[AssetRecord] = []
        groups: list[AssetGroup] = []
        for summary in snapshot.assets:
            asset = self.get_asset(summary.asset_ref, include_superseded=True)
            assert asset is not None
            assets.append(asset)
        for summary in snapshot.groups:
            group = self.get_group(summary.group_ref, include_superseded=True)
            assert group is not None
            groups.append(group)
        return assets, groups

    def _snapshot_digest(
        self,
        assets: list[AssetRepositorySnapshotAsset],
        groups: list[AssetRepositorySnapshotGroup],
    ) -> str:
        payload = {
            "assets": [item.model_dump(mode="json") for item in assets],
            "groups": [item.model_dump(mode="json") for item in groups],
            "repository_schema_version": SCHEMA_VERSION,
        }
        return sha256_json(payload)

    def _allocate(self, entity_type: str) -> str:
        row = self.connection.execute("SELECT next_value FROM id_sequences WHERE entity_type=?", (entity_type,)).fetchone()
        value = row["next_value"]
        self.connection.execute("UPDATE id_sequences SET next_value=? WHERE entity_type=?", (value + 1, entity_type))
        return f"{'asset://A' if entity_type == 'asset' else 'group://G'}{value:04d}"

    def _asset_from_row(self, row: sqlite3.Row) -> AssetRecord:
        lineage_row = self.connection.execute("SELECT * FROM asset_lineage WHERE asset_ref=?", (row["asset_ref"],)).fetchone()
        lineage = None
        if lineage_row:
            parents = [
                item["parent_asset_ref"]
                for item in self.connection.execute(
                    "SELECT parent_asset_ref FROM asset_parents WHERE asset_ref=? ORDER BY parent_order", (row["asset_ref"],)
                )
            ]
            lineage = AssetLineage(
                parent_asset_refs=parents,
                derivation_type=lineage_row["derivation_type"],
                executor_id=lineage_row["executor_id"],
                provider=lineage_row["provider"],
                model=lineage_row["model"],
                prompt_template_version=lineage_row["prompt_template_version"],
                prompt_sha256=lineage_row["prompt_sha256"],
                parameters_sha256=lineage_row["parameters_sha256"],
                derivation_signature=lineage_row["derivation_signature"],
                created_at=datetime.fromisoformat(lineage_row["created_at"]),
            )
        return AssetRecord(
            asset_ref=row["asset_ref"],
            filename=row["filename"],
            object_key=row["object_key"],
            content_sha256=row["content_sha256"],
            media_type=row["media_type"],
            module=row["module"],
            category_id=row["category_id"],
            category_path=json.loads(row["category_path_json"]),
            asset_role=row["asset_role"],
            case_label=row["case_label"],
            industry=row["industry"],
            description=row["description"],
            width=row["width"],
            height=row["height"],
            orientation=Orientation(row["orientation"]),
            animated=bool(row["animated"]),
            source_kind=SourceKind(row["source_kind"]),
            origin_type=row["origin_type"],
            evidence_class=EvidenceClass(row["evidence_class"]),
            claims=json.loads(row["claims_json"]),
            status=AssetStatus(row["status"]),
            superseded_by=row["superseded_by"],
            lineage=lineage,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _group_from_row(self, row: sqlite3.Row) -> AssetGroup:
        members = [
            AssetGroupMember(
                member_key=item["member_key"], asset_role=item["asset_role"], asset_ref=item["asset_ref"], order=item["member_order"]
            )
            for item in self.connection.execute(
                "SELECT * FROM asset_group_members WHERE group_ref=? ORDER BY member_order", (row["group_ref"],)
            )
        ]
        return AssetGroup(
            group_ref=row["group_ref"],
            group_type=row["group_type"],
            pattern_id=row["pattern_id"],
            category_id=row["category_id"],
            members=members,
            status=AssetStatus(row["status"]),
            superseded_by=row["superseded_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
