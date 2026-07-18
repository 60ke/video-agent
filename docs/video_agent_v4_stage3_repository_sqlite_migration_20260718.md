# Video Agent V4 Stage 3: Repository, SQLite, ObjectStore And Legacy Migration

Status: formal design revised against Stage0 Rev3 and Stage1/2 implementation; implementation pending

Date: 2026-07-18

## 1. Authority And Scope

This design implements architecture item §8-4 from:

- `docs/video_agent_v4_architecture_framework_rev3_20260717.md`;
- `docs/video_agent_v4_stage0_golden_scenario_rev3_20260718.md`;
- `docs/video_agent_v4_stage2_capability_and_asset_contracts_20260717.md`.

Stage 3 provides the authoritative persistence boundary for V4 assets:

1. repository interfaces for assets, lineage, groups and configured bindings;
2. a transactional SQLite implementation;
3. a local filesystem ObjectStore implementation;
4. immutable register and explicit supersede operations;
5. deterministic repository snapshots for Run freezing;
6. a one-time, idempotent migration from the V3 catalog, relationships and
   derived manifests;
7. an explicit import path for future local assets.

Stage 3 does not select assets for a scene, execute GPT Image, assign effects or
SFX, compile word timing, or switch the production pipeline to V4. Those remain
Stages 4 through 7.

## 2. Design Laws

### 2.1 Repository Is The Runtime Authority

After a successful cutover, runtime code reads `AssetRepository`; it does not
read `assets/catalog.json`, `assets/relationships.json`, derived registries or
batch manifests directly. Legacy JSON remains migration evidence until Stage 7
removes it from the main path.

The repository stores semantic records. The ObjectStore stores media bytes.
Neither layer infers scene meaning at query time.

### 2.2 Import Is Acceptance

Every file under the project `assets/` production boundary has already passed
human review outside this project. Import validates only:

- file existence and decodability;
- content SHA256;
- media type, dimensions and orientation;
- canonical registry references;
- lineage, evidence and group integrity.

There is no review, approval, rejection or AI visual-quality state in the V4
database or import report.

### 2.3 Immutable Content And Identity

An `asset_ref` identifies one immutable semantic record and one immutable object
hash. The repository never updates filename, object key, content hash, role,
category, evidence or lineage in place.

Replacing bytes or semantic identity performs:

```text
register new asset
-> mark old asset superseded
-> old.superseded_by = new.asset_ref
```

Historical Runs can still resolve superseded records and their objects. New
queries exclude them by default.

### 2.4 Relative Object Keys Only

The local store root is the project `assets/` directory. Database records store
POSIX keys relative to that root, for example:

```text
results/柯幻熊猫_文生图_文化墙_社区服务_结果图_01.png
derived/generated/文化墙_result_to_flat_plan_211fef200bec.png
```

Host paths, drive letters and `file://` URLs never enter V4 records, frozen Run
snapshots or model context.

### 2.5 Migration Is Deterministic And Fail-Loud

A fresh repository migrated from the same input bytes and migration mapping
version receives the same ordered `asset://Axxxx` and `group://Gxxxx` refs.

Migration does not guess through an invalid record. It records a structured
error and rolls back the entire migration transaction. A dry run produces the
same plan and diagnostics without writing records.

## 3. Module Layout

```text
video_agent/assets/v4/
  __init__.py
  repository.py          # protocols, queries, snapshots and domain errors
  sqlite_repository.py   # SQLite implementation and schema migrations
  object_store.py        # ObjectStore protocol and local implementation
  import_service.py      # explicit V4 import and supersede workflows
  legacy_migration.py    # V3 input adapters, mapping and migration planner

config/assets.v4.json    # local repository and object-store locations

var/v4/
  assets.sqlite3         # ignored local runtime database
  migrations/            # ignored reports and dry-run plans
```

Tests use temporary database and object-store roots. Production defaults are
resolved relative to the repository root and can be overridden by CLI flags.

## 4. Public Repository Boundary

### 4.1 Query Models

```python
@dataclass(frozen=True)
class AssetQuery:
    category_ids: tuple[str, ...] = ()
    asset_roles: tuple[str, ...] = ()
    source_kinds: tuple[SourceKind, ...] = ()
    orientations: tuple[Orientation, ...] = ()
    claims: tuple[str, ...] = ()
    active_only: bool = True

@dataclass(frozen=True)
class GroupQuery:
    group_types: tuple[str, ...] = ()
    pattern_ids: tuple[str, ...] = ()
    category_ids: tuple[str, ...] = ()
    member_roles: tuple[str, ...] = ()
    active_only: bool = True
```

Empty tuples mean no filter. Query implementations are deterministic and return
ascending `asset_ref` or `group_ref` order unless a later selector applies an
explicit ranking.

`active_only=true` applies two lifecycle filters: the record itself must be
active, and a derived asset is excluded when any direct or transitive parent is
superseded. Historical lookup remains available through explicit get/freeze
operations. This prevents a still-active child from remaining a new-Run
candidate after its semantic source has been replaced.

### 4.2 Repository Protocol

```python
class AssetRepository(Protocol):
    def get_asset(self, asset_ref: str, *, include_superseded: bool = True) -> AssetRecord | None: ...
    def query_assets(self, query: AssetQuery) -> list[AssetRecord]: ...
    def register_asset(self, draft: AssetDraft) -> AssetRecord: ...
    def supersede_asset(self, old_ref: str, replacement: AssetDraft) -> AssetRecord: ...
    def find_by_derivation_signature(self, signature: str) -> AssetRecord | None: ...

    def get_group(self, group_ref: str, *, include_superseded: bool = True) -> AssetGroup | None: ...
    def query_groups(self, query: GroupQuery) -> list[AssetGroup]: ...
    def register_group(self, draft: AssetGroupDraft) -> AssetGroup: ...
    def supersede_group(self, old_ref: str, replacement: AssetGroupDraft) -> AssetGroup: ...

    def bind_configured_asset(self, config_key: str, asset_ref: str) -> None: ...
    def configured_asset(self, config_key: str) -> AssetRecord | None: ...
    def freeze(self, asset_refs: list[str], group_refs: list[str]) -> AssetRepositorySnapshot: ...
```

`AssetDraft` and `AssetGroupDraft` contain all contract fields except the
repository-assigned ref and creation timestamp. The repository returns the full
Stage 2 contract after boundary validation.

### 4.3 Transaction Boundary

SQLite exposes an internal transaction context used by migration and compound
imports. Public single-record methods each use one immediate transaction.

The repository owns ref allocation. Callers cannot choose `Axxxx` or `Gxxxx`.
Legacy IDs are stored as mappings, never reused as V4 refs.

## 5. SQLite Schema

SQLite runs with foreign keys enabled, WAL mode and an explicit schema version.
All JSON is canonical UTF-8 JSON with sorted keys.

### 5.1 Core Tables

```sql
CREATE TABLE repository_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE id_sequences (
  entity_type TEXT PRIMARY KEY CHECK(entity_type IN ('asset', 'group')),
  next_value INTEGER NOT NULL CHECK(next_value >= 1)
);

CREATE TABLE assets (
  asset_ref TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  object_key TEXT NOT NULL UNIQUE,
  content_sha256 TEXT NOT NULL,
  media_type TEXT NOT NULL,
  module TEXT,
  category_id TEXT,
  category_path_json TEXT NOT NULL,
  asset_role TEXT NOT NULL,
  case_label TEXT,
  industry TEXT,
  description TEXT,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  orientation TEXT NOT NULL,
  animated INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  origin_type TEXT NOT NULL,
  evidence_class TEXT NOT NULL,
  claims_json TEXT NOT NULL,
  status TEXT NOT NULL,
  superseded_by TEXT REFERENCES assets(asset_ref),
  created_at TEXT NOT NULL
);

CREATE TABLE asset_lineage (
  asset_ref TEXT PRIMARY KEY REFERENCES assets(asset_ref),
  derivation_type TEXT NOT NULL,
  executor_id TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  prompt_template_version TEXT,
  prompt_sha256 TEXT,
  parameters_sha256 TEXT NOT NULL,
  derivation_signature TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE asset_parents (
  asset_ref TEXT NOT NULL REFERENCES assets(asset_ref),
  parent_asset_ref TEXT NOT NULL REFERENCES assets(asset_ref),
  parent_order INTEGER NOT NULL,
  PRIMARY KEY(asset_ref, parent_asset_ref),
  UNIQUE(asset_ref, parent_order)
);

CREATE TABLE asset_groups (
  group_ref TEXT PRIMARY KEY,
  group_type TEXT NOT NULL,
  pattern_id TEXT NOT NULL,
  category_id TEXT NOT NULL,
  status TEXT NOT NULL,
  superseded_by TEXT REFERENCES asset_groups(group_ref),
  created_at TEXT NOT NULL
);

CREATE TABLE asset_group_members (
  group_ref TEXT NOT NULL REFERENCES asset_groups(group_ref),
  member_key TEXT NOT NULL,
  asset_role TEXT NOT NULL,
  asset_ref TEXT NOT NULL REFERENCES assets(asset_ref),
  member_order INTEGER NOT NULL,
  PRIMARY KEY(group_ref, member_key),
  UNIQUE(group_ref, member_order)
);

CREATE INDEX idx_assets_active_role_category_orientation
  ON assets(status, asset_role, category_id, orientation);
CREATE UNIQUE INDEX idx_asset_lineage_derivation_signature
  ON asset_lineage(derivation_signature);
CREATE INDEX idx_asset_groups_active_pattern_category
  ON asset_groups(status, pattern_id, category_id);
CREATE INDEX idx_asset_group_members_asset
  ON asset_group_members(asset_ref);
```

### 5.2 Operational Tables

```sql
CREATE TABLE configured_asset_bindings (
  config_key TEXT PRIMARY KEY,
  asset_ref TEXT NOT NULL REFERENCES assets(asset_ref),
  updated_at TEXT NOT NULL
);

CREATE TABLE legacy_id_map (
  source_name TEXT NOT NULL,
  legacy_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK(entity_kind IN ('asset', 'group')),
  v4_ref TEXT NOT NULL,
  source_payload_json TEXT NOT NULL,
  PRIMARY KEY(source_name, legacy_id)
);

CREATE TABLE migration_runs (
  migration_key TEXT PRIMARY KEY,
  mapping_version TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL,
  report_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
```

`legacy_id_map.source_payload_json` preserves legacy-only metadata for audit and
debugging. It is not exposed as V4 runtime asset metadata.

Indexes cover active role/category/orientation queries, lineage signatures,
group type/category and group membership by asset.

### 5.3 Database Invariants

Repository code and database constraints jointly enforce:

- immutable semantic fields after insert;
- only `active -> superseded` lifecycle transition;
- no supersede self-reference or cycle;
- referenced parent assets and group members exist;
- derived children cannot register before their parents;
- object key and content hash match ObjectStore inspection;
- configured bindings target active assets and enabled config keys;
- a group is validated against the same frozen Capability Registry used by the
  operation;
- every group declares an enabled `pattern_id`, and its group type, member keys,
  roles, required members and order exactly match that Relation Pattern;
- active candidate queries exclude descendants of superseded parents;
- a derivation signature resolves to at most one immutable derived asset.

## 6. ObjectStore

### 6.1 Protocol

```python
class AssetObjectStore(Protocol):
    def resolve(self, object_key: str) -> Path: ...
    def inspect(self, object_key: str) -> MediaObjectInfo: ...
    def verify(self, object_key: str, expected_sha256: str) -> MediaObjectInfo: ...
    def put_file(self, source: Path, object_key: str) -> MediaObjectInfo: ...
```

`MediaObjectInfo` contains object key, SHA256, byte size, MIME type, width,
height, orientation and `animated`.

### 6.2 Local Store Rules

- resolve the final path beneath the configured root and reject traversal;
- decode raster images with Pillow;
- probe video dimensions with the project FFmpeg/ffprobe runtime;
- reject audio from the visual asset repository; SFX remains Stage 5 data;
- `put_file` copies to a sibling temporary path, fsyncs, verifies, then performs
  atomic replace only when the target does not exist;
- an existing target with the same hash is reused;
- an existing target with a different hash fails and requires a new object key;
- migration uses `inspect` on existing `assets/` objects and does not copy or
  rewrite their bytes.

## 7. Explicit Import And Supersede

### 7.1 Import Manifest

Future imports use a named-object manifest rather than filename-only inference:

```json
{
  "schema_version": 1,
  "assets": [
    {
      "source": "C:/staging/文化墙01.png",
      "object_key": "results/柯幻熊猫_文生图_文化墙_社区服务_结果图_02.png",
      "module": "文生图",
      "category_id": "文生图/文化墙",
      "category_path": ["文化墙"],
      "asset_role": "result_image",
      "case_label": "社区服务",
      "description": "社区服务中心文化墙结果图",
      "source_kind": "original",
      "origin_type": "imported",
      "evidence_class": "E0_source_evidence",
      "claims": ["feature_can_generate_result"]
    }
  ],
  "groups": []
}
```

The source path is accepted only by the local CLI boundary and never persisted.
The copied object key and generated `asset_ref` are persisted.

### 7.2 Import Flow

```text
parse manifest
-> validate registry IDs
-> inspect source
-> build AssetDraft
-> preflight every asset and group
-> put immutable object bytes
-> register records in one DB transaction
-> write import report
```

If database registration fails, newly copied unreferenced files are listed as
orphans in the report and may be safely removed by an explicit cleanup command.
No existing object is deleted automatically.

### 7.3 Supersede Flow

Supersede requires the old ref and a complete replacement draft. It validates
the replacement first, registers it, transitions the old record and writes both
changes in one transaction. It never rewrites relationships automatically;
callers explicitly supersede affected groups so causal history remains honest.

## 8. Legacy Migration

### 8.1 Inputs And Precedence

The migration consumes these authoritative inputs, in precedence order:

1. `assets/catalog.json` as the primary deduplicated visual inventory;
2. `assets/derived/generated/registry.json` to enrich or add generated assets;
3. `assets/relationships.json` for causal/comparison/process relationships;
4. `assets/derived/sites/柯幻熊猫/文生图/功能入口/manifest.json`;
5. `assets/derived/sites/柯幻熊猫/文生图/参数面板/manifest.json`;
6. `assets/derived/sites/柯幻熊猫/文生图/参数面板序列/manifest.json`;
7. `assets/derived/workflow_scenes/manifest.json`;
8. site manifests enrich lineage, while parameter sequences and workflow
   manifests may create ordered process groups;
9. `assets/results/_library_manifest.json` to enrich descriptions, case labels
   and industry metadata when the file hash matches.

The migration does not scan or infer records from `assets/imports/`, `cases/`,
`output/`, `.codex-remote-attachments/`, audio/SFX catalogs or arbitrary nested
JSON files. New files outside the authoritative list enter V4 only through the
explicit import manifest in §7.

The generated registry and manifests do not create a second record when their
canonical object key already exists in the Catalog. They enrich the migration
draft and legacy mappings.

Unknown legacy review/quality fields are preserved only in
`legacy_id_map.source_payload_json`; they never enter `AssetRecord`.

### 8.2 Canonical Object Key

Legacy path conversion is explicit:

- `assets/...` -> strip the `assets/` prefix;
- an absolute path beneath the configured ObjectStore root -> relativize;
- an absolute metadata/staging path outside the store -> retain only in the
  legacy audit payload, never as the object key;
- a primary asset path outside the store -> migration error;
- separator conversion occurs in the migration adapter before strict V4
  contract construction.

The adapter verifies the object bytes and ignores stale legacy width, height,
orientation or hash values when they disagree with the actual file by failing
the plan. It does not silently repair the source record.

### 8.3 Role Mapping

The initial migration mapping is versioned as `legacy-v3-to-v4.1`:

| Legacy role | V4 role | Notes |
|---|---|---|
| `site_home` | `site_home` | unchanged |
| `feature_list` | `feature_list` | unchanged |
| `feature_entry` | `feature_entry` | unchanged |
| `feature_form_params` | `parameter_panel` | canonical rename |
| `result_image` | `result_image` | unchanged |
| `reference_image` | `reference_image` | unchanged |
| `plane_result` | `flat_plan` | canonical rename |
| `editor_workspace` | `editor_page` | canonical rename |
| `editor_local_modal` | `editor_modal` | canonical rename |
| generated edited result | `edited_result` | based on `derive_kind` |
| `gallery_preview` | `result_image` | `gallery_preview` becomes derivation type, not role |
| `brand_logo` | `brand_logo` | official logo only |
| `outro` | `outro` | unchanged |
| `brand_ip` | none | disabled and absent from the production library |

Any unknown role fails migration and is reported. It is not converted to a
generic image role.

### 8.4 Category Mapping

Legacy `semantic_path` is normalized through the frozen Category Registry:

- exact canonical `module/path` first;
- enabled alias resolution second;
- infrastructure roles that do not require a category store null category;
- category-required roles with no exact or alias match fail migration.

Filename tokens do not override an explicit valid semantic path. Potentially
misclassified historical assets are included in a migration warning report for
manual correction through later explicit supersede/import, not silently moved.

### 8.5 Source, Evidence And Claim Mapping

Mapping is conservative:

- site screenshots, curated result images, curated reference images and the
  official logo are `original`;
- byte-preserving local crop/reframe operations are `derived/E1` only when the
  parent hash and faithful transform are recorded;
- GPT Image outputs, reconstructed references, edited states and generated flat
  plans are `derived/E2`;
- outro and decorative assets are `E3`;
- E2/E3 claims are always empty;
- `curated_result_image` and equivalent confirmed result claims map to
  `feature_can_generate_result`;
- original site screenshot roles map to `real_website_screenshot`;
- unknown marketing/tag strings do not become V4 Claim IDs;
- a derived asset with no resolvable parent fails migration instead of being
  relabeled original.

Provider/model/prompt data, derivation kind and `derivative_key` populate
`AssetLineage`. Missing local-transform prompt hashes remain null, while the
parameters hash and deterministic derivation signature are always generated.

### 8.6 Group Reconstruction

Group reconstruction is driven by registered Relation Patterns, not by broad
`group_type` membership or filename similarity. One legacy relationship may
produce more than one group only when each output satisfies a different
explicit pattern. Duplicate asset refs within one group are removed before
pattern validation.

The deterministic algorithm is:

1. `reference_image + result_image + flat_plan` creates exactly one
   `reference_result_plan` group with `group_type=causal`. If a required member
   is missing, no partial causal group is invented; migration fails with the
   relationship ID and missing member key.
2. An editing workflow from relationship fields or
   `assets/derived/workflow_scenes/manifest.json` creates exactly one
   `editor_sequence` group with `group_type=process`: `source_result ->
   editor_page -> edited_result`. The modal is not required by the Stage0
   pattern and is not inserted into this group. If legacy
   `editor_composite_asset_id == result_asset_id`, that duplicate is not
   relabeled as `editor_page`; a distinct editor-page asset must come from the
   workflow manifest or migration fails.
3. `comparison` is never inferred merely because a result and edited result
   coexist. It is created only when a future authoritative source explicitly
   declares a comparison pattern. Editing remains a process relationship.
4. The same assets may legally participate in causal and process groups. Each
   group keeps its own `pattern_id`, canonical members and audit mapping.

Parameter sequence manifests create `parameter_callout_sequence` groups with
`group_type=process` and member keys:

```text
base -> stage -> final
```

All three members retain role `parameter_panel`; the member key describes the
sequence state. No group is registered until the frozen Relation Pattern
validates every required member, role and order.

### 8.7 Configured Bindings

Migration binds:

- `default_brand_logo` to the only active `brand_logo` record named
  `柯幻熊猫_LOGO.png`;
- `default_outro` to the canonical active outro record.

Missing or ambiguous configured assets fail the migration plan.

### 8.8 Deterministic Ordering And IDs

On a fresh database, asset drafts are sorted by:

```text
canonical object_key, content_sha256, legacy source name, legacy ID
```

Parent assets are inserted before derived children using a lineage DAG. Groups
are sorted by pattern ID, group type, category and ordered member refs after
assets exist.

The same completed migration key is a no-op and returns the persisted report.
A changed input fingerprint creates a new migration key, but conflicting object
keys or changed bytes fail and require explicit import/supersede. Migration does
not mutate an existing record to match a changed legacy JSON file.

## 9. Migration Command And Reports

CLI surface introduced in Stage 3:

```text
python main.py v4-assets migrate-legacy [--dry-run] [--db PATH] [--object-root PATH]
python main.py v4-assets import --manifest PATH [--db PATH] [--object-root PATH]
python main.py v4-assets inspect [--asset-ref REF] [--db PATH]
python main.py v4-assets audit [--db PATH] [--object-root PATH]
```

The migration report is a named JSON object containing:

- mapping version and input file hashes;
- migration key and dry-run flag;
- planned/inserted/reused asset and group counts;
- legacy-to-V4 ref mappings;
- role/category/evidence transformations;
- warnings for suspicious category/filename combinations;
- structured failures with source file, legacy ID and field path;
- configured asset bindings;
- repository snapshot hash after success.

No report contains API keys or external staging paths outside the legacy audit
section. Model-facing payloads never consume the legacy audit section.

## 10. Repository Snapshot

Stage 3 adds a strict `AssetRepositorySnapshot` contract:

```json
{
  "snapshot_id": "asset-snapshot://sha256/...",
  "created_at": "2026-07-18T00:00:00Z",
  "repository_schema_version": 1,
  "content_sha256": "...",
  "assets": [
    {
      "asset_ref": "asset://A0001",
      "object_key": "results/...png",
      "content_sha256": "...",
      "status": "active",
      "lineage_sha256": null,
      "evidence_class": "E0_source_evidence",
      "claims": ["feature_can_generate_result"]
    }
  ],
  "groups": [
    {
      "group_ref": "group://G0001",
      "content_sha256": "..."
    }
  ]
}
```

Snapshots preserve requested order only where group member order is semantic;
top-level assets and groups are sorted by ref before hashing. A snapshot is a
fingerprint and tamper-detection artifact, not a second self-contained asset
database. The authoritative full records remain in SQLite. Restoring a Run:

1. validates the snapshot and every summary hash;
2. resolves listed refs from SQLite, including explicitly requested superseded
   historical records;
3. verifies each full record and object still match the frozen hashes;
4. fails loudly when SQLite or ObjectStore can no longer reproduce the Run.

Snapshot consumers never re-run an active-only query to approximate a
historical Run.

### 10.1 Stage 6 Evidence Freeze Amendment

Stage 6 Claim compilation must not query the live repository. Therefore the
frozen asset summary includes `evidence_class` and `claims` in addition to
identity, object hash, lifecycle and lineage hash. Both fields are copied from
the full `AssetRecord` at freeze time and participate in the snapshot content
hash and snapshot ID.

This does not turn the snapshot into a second asset database: category, role,
dimensions and other selection metadata remain authoritative in SQLite. It is
the minimal immutable evidence projection required to verify claims for the
exact assets already selected into a Run. Adding these fields requires a
repository snapshot schema-version bump; no compatibility reader is added for
V4 Runs created before the amendment.

## 11. Failure And Rollback Semantics

- schema migration uses a SQLite transaction and records the schema version;
- legacy migration plans all records before opening its write transaction;
- any record, lineage, group or configured-binding failure rolls back the whole
  migration run;
- migration never moves, renames or deletes legacy media bytes;
- `--dry-run` performs full parsing, media inspection and validation;
- a successful migration can be rolled back by restoring the prior SQLite file;
  legacy files remain unchanged;
- on a fresh database, deleting the database and rerunning produces the same
  refs from the same inputs;
- ObjectStore hash mismatch is a hard error, not a warning;
- repository integrity audit detects missing objects, hash drift, invalid refs,
  broken lineage, cycles, group inconsistencies and stale configured bindings.
- `var/v4/` is required in `.gitignore`; SQLite databases, WAL/SHM files,
  migration plans and reports must never be committed.

## 12. Tests And Completion Definition

Stage 3 implementation is complete only when:

1. SQLite initializes and upgrades its schema idempotently;
2. LocalObjectStore rejects traversal, host paths and conflicting overwrites;
3. register/query/get operations round-trip strict Stage 2 contracts;
4. active queries exclude superseded records and descendants of superseded
   parents, while explicit historical lookup still resolves them;
5. supersede is atomic and cycle-safe for assets and groups;
6. derived registration requires existing parents and a valid lineage DAG;
7. group registration requires existing members and exact frozen Relation
   Pattern validity, including pattern ID, required keys, roles and order;
8. configured bindings validate enabled keys and active target roles;
9. derivation signatures are indexed, unique and reusable through
   `find_by_derivation_signature`;
10. repository snapshots are deterministic, detect tampering and restore full
    records from SQLite rather than acting as a second database;
11. import copies and registers an external file without persisting its source
    host path;
12. legacy dry run reads only the authoritative path list and reports all
    mapping decisions;
13. legacy migration succeeds on a fresh temporary repository, is idempotent on
    rerun and rolls back completely on injected failure;
14. migrated assets contain no review/approval fields or absolute object keys;
15. generated assets preserve parent lineage and derivation signatures;
16. causal and process groups are reconstructed only from authoritative
    relationships/manifests; result+edited never auto-creates comparison;
17. the official logo and outro configured bindings resolve uniquely;
18. an audit verifies every migrated object hash and relationship;
19. `var/v4/` is ignored by Git;
20. Stage 1+2 tests and the Stage0 real Scope/Scene execution still pass;
21. `docs/v4_implementation_progress.md` records commands, counts, assumptions
    and the next Stage 4 continuation point.
