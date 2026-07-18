# Video Agent V4 Stage 2: Capability and Asset Domain Contracts

Status: formal design, implementation follows this document

Date: 2026-07-17

## 1. Authority And Scope

This design implements architecture item §8-3 from:

- `docs/video_agent_v4_architecture_framework_rev3_20260717.md`
- `docs/video_agent_v4_stage0_golden_scenario_rev3_20260718.md`
- `docs/video_agent_v4_stage1_semantic_contract_and_ai_runtime_design_20260717.md`

Stage 2 defines and validates:

1. the shared Capability Registry contract and frozen registry snapshots;
2. Category and Asset Role registries;
3. the semantic registries already consumed by Stage 1;
4. `AssetRecord`, `AssetLineage`, `AssetGroup`, lifecycle and evidence contracts;
5. cross-contract invariants at registry and asset-domain boundaries.

Stage 2 does not implement SQLite, object storage, selection, derivation execution,
motion, SFX, timing compilation, rendering or legacy catalog migration. Those are
implemented in Stages 3 through 7 against the contracts frozen here.

## 2. Design Laws

### 2.1 Dynamic Capabilities

Category, asset role, visual structure, operation intent, claim, relation group
type and configured asset IDs are stable strings validated against the current
registry snapshot. They are not permanent Python `Literal` values.

The only closed enums in this stage are structural protocol values whose meaning
cannot be extended without a schema upgrade:

- `source_kind`: `original | derived`;
- `asset_status`: `active | superseded`;
- `orientation`: `landscape | portrait | square`;
- the existing four `EvidenceClass` IDs.

### 2.2 Active Means Usable

Human visual review happens outside this project. An imported asset that reaches
the V4 repository with `status=active` is considered available for production.
There is no `reviewed`, `unreviewed`, `human_approved` or AI visual-review field in
the V4 asset contract.

Runtime checks verify contract integrity, file existence, content hash, media
metadata, registry references and relationship consistency. They do not approve
visual quality.

### 2.3 Immutable Identity

Changing media content creates a new `asset_ref`. Existing records are never
silently overwritten. Replaced records become `superseded` and point to the new
record. Frozen Runs retain the old `asset_ref`, object hash and lineage summary.

### 2.4 Evidence Discipline

`source_kind` describes whether bytes are original or derived. `evidence_class`
describes what the asset may prove. They are separate fields.

`E2_semantic_derivative` and `E3_decorative` cannot carry factual Claim IDs.
Faithful derivatives retain evidence only through an explicit lineage chain back
to a supporting source asset.

## 3. Capability Registry Contract

### 3.1 Registry Document

Every registry file is a versioned document:

```json
{
  "registry_id": "asset_role",
  "version": "2026.07.17.1",
  "schema_version": 1,
  "entries": []
}
```

Common requirements:

- `registry_id` is unique within a Hub;
- `version` changes whenever semantic content changes;
- entry IDs are unique and never reused for a different meaning;
- disabling uses `enabled=false`; entries are not physically deleted;
- `schema_version` upgrades the document shape, not the business version;
- unknown top-level and entry fields fail validation;
- a behavior entry with a non-null handler is resolved and validated at startup;
- a data-only entry may have no handler.

### 3.2 Base Entry

```json
{
  "id": "result_image",
  "display_name": "结果图",
  "description": "具体功能生成或导入的结果图",
  "enabled": true,
  "schema_version": 1,
  "handler": null,
  "capabilities": {}
}
```

`capabilities` contains registry-specific declarative constraints. Business code
must read typed entry fields first; it must not inspect arbitrary capability keys
to recreate a hidden second schema.

### 3.3 Category Registry

Category is the only function taxonomy. `module` and `category_path` are frozen
views of the same hierarchy, not separate classification systems.

```json
{
  "id": "文生图/文化墙",
  "display_name": "文化墙",
  "module": "文生图",
  "category_path": ["文化墙"],
  "aliases": [],
  "scope_eligible": true,
  "enabled": true,
  "schema_version": 1
}
```

Rules:

- `id == module + '/' + '/'.join(category_path)`;
- aliases are unique after Unicode and whitespace normalization;
- an alias cannot resolve to two enabled categories;
- `scope_eligible=false` allows infrastructure categories such as `网站/主页`
  without exposing them as video feature scope;
- category hierarchy changes use a new ID plus explicit migration. Existing
  historical assets retain the old frozen category reference.

### 3.4 Asset Role Registry

```json
{
  "id": "result_image",
  "display_name": "结果图",
  "description": "具体功能的生成结果",
  "requires_category": true,
  "allowed_source_kinds": ["original", "derived"],
  "default_derived_evidence": "E2_semantic_derivative",
  "allowed_parent_roles": ["result_image", "reference_image"],
  "allowed_group_types": ["causal", "comparison", "process"],
  "allowed_derivation_ids": [],
  "display_capability_tags": ["single", "gallery", "sequence"],
  "enabled": true,
  "schema_version": 1
}
```

Rules:

- `allowed_source_kinds` controls candidate eligibility;
- `requires_category=true` requires a canonical Category ID on each asset;
- derivation IDs are stable references validated once the Derivation Registry is
  loaded in Stage 5;
- group types and display tags are capability references, not renderer branches;
- role meaning is semantic. A derivation purpose such as `gallery_normalized`
  does not become a new asset role.

### 3.5 Semantic Registries

Stage 2 also formalizes the registries already used by Stage 1:

- `visual_structure`;
- `operation_intent`;
- `claim`;
- `group_type`;
- `configured_asset`.

Claim entries add `required_evidence_classes`. Group type entries may declare
`ordered=true` and permitted member-role patterns. The first group types are
`causal`, `comparison` and ordered `process`, but these remain configuration data.

### 3.6 CapabilityRegistryHub

The Hub owns loaded typed registry documents and exposes:

```python
hub.registry(registry_id)
hub.entry(registry_id, entry_id, include_disabled=False)
hub.require_entry(registry_id, entry_id)
hub.resolve_category(text)
hub.freeze(output_path)
hub.snapshot()
```

The Hub validates:

- registry and entry uniqueness;
- category ID/path/alias consistency;
- all cross-registry references that target an already loaded registry;
- handler existence for behavior entries;
- Claim evidence IDs;
- enabled/disabled semantics.

Later stages register additional typed registry loaders with the same Hub rather
than creating another registry system.

### 3.7 Frozen Snapshot

Every Run writes one immutable snapshot:

```json
{
  "snapshot_id": "registry-snapshot://sha256/...",
  "created_at": "2026-07-17T00:00:00Z",
  "content_sha256": "...",
  "registries": [
    {
      "registry_id": "category",
      "version": "2026.07.17.1",
      "content_sha256": "...",
      "document": {}
    }
  ]
}
```

The content hash is calculated from canonical JSON excluding `created_at` and the
derived hash fields. Resume fingerprints use the snapshot hash. Historical Runs
read their frozen snapshot rather than current config files.

## 4. Asset Domain Contracts

### 4.1 Asset References And Object Keys

- `asset_ref`: `asset://A` followed by at least four decimal digits;
- `group_ref`: `group://G` followed by at least four decimal digits;
- IDs are repository-assigned and human-readable;
- model context may receive `asset_ref` and relative metadata, never an absolute
  host path;
- `object_key` is a normalized relative POSIX path with no drive, URI, `..` or
  leading slash;
- `filename` must equal the last object-key segment.

### 4.2 AssetRecord

```json
{
  "asset_ref": "asset://A0123",
  "filename": "柯幻熊猫_文生图_文化墙_社区服务_结果图_01.png",
  "object_key": "results/文生图/文化墙/社区服务/结果图_01.png",
  "content_sha256": "...",
  "media_type": "image/png",
  "module": "文生图",
  "category_id": "文生图/文化墙",
  "category_path": ["文化墙"],
  "asset_role": "result_image",
  "case_label": "社区服务",
  "industry": null,
  "description": "社区服务中心室内文化墙效果图",
  "width": 2048,
  "height": 1152,
  "orientation": "landscape",
  "animated": false,
  "source_kind": "original",
  "origin_type": "imported",
  "evidence_class": "E0_source_evidence",
  "claims": ["feature_can_generate_result"],
  "status": "active",
  "superseded_by": null,
  "lineage": null,
  "created_at": "2026-07-17T00:00:00Z"
}
```

Required fields are identity, relative object location, content hash, media
metadata, canonical category, role, source kind, evidence class and lifecycle.
Description, case label and industry are optional query metadata, not a second
taxonomy.

No independent style/color/visual-tag ontology is introduced in V4 Stage 2.

### 4.3 AssetLineage

```json
{
  "parent_asset_refs": ["asset://A0123"],
  "derivation_type": "result_to_editor_workspace",
  "executor_id": "gpt_image",
  "provider": "configured-provider",
  "model": "configured-model",
  "prompt_template_version": "editor-workspace-v2",
  "prompt_sha256": "...",
  "parameters_sha256": "...",
  "derivation_signature": "...",
  "created_at": "2026-07-17T00:00:00Z"
}
```

Rules:

- a derived asset requires non-empty lineage and at least one parent;
- an original asset must have `lineage=null`;
- parent references are unique and cannot include the child;
- `derivation_type` is validated against the Derivation Registry in Stage 5;
- `derivation_signature` is deterministic over parent refs and content hashes,
  derivation definition version, normalized parameters and prompt fingerprint;
- prompt fields may be null for faithful local transforms, but the executor and
  parameters fingerprint remain required;
- lineage is immutable after registration.

### 4.4 Asset Lifecycle

`active` assets participate in new queries. `superseded` assets remain readable
for historical Runs and lineage traversal but are excluded from new candidate
queries by default.

Rules:

- `superseded` requires `superseded_by`;
- `active` requires `superseded_by=null`;
- a record cannot supersede itself;
- replacement compatibility and cycle detection are repository-domain checks;
- derived children of a superseded parent remain available to historical Runs
  but are excluded from new queries unless explicitly reactivated after
  validation or regenerated from the replacement parent.

### 4.5 EvidenceClass

The stable IDs are preserved exactly:

```text
E0_source_evidence
E1_faithful_derivative
E2_semantic_derivative
E3_decorative
```

Contract rules:

- E0 requires `source_kind=original`;
- E1 and E2 require `source_kind=derived` and lineage;
- E3 may be original or derived;
- E2 and E3 require `claims=[]`;
- E1 does not automatically inherit every parent Claim. A compiler later proves
  support by traversing faithful lineage to a source carrying the same Claim;
- evidence can stay equal or decrease through a derivation chain, never increase
  merely because multiple parents are combined.

### 4.6 AssetGroup

```json
{
  "group_ref": "group://G0012",
  "group_type": "causal",
  "category_id": "文生图/文化墙",
  "members": [
    {
      "member_key": "reference_image",
      "asset_role": "reference_image",
      "asset_ref": "asset://A0122",
      "order": 1
    },
    {
      "member_key": "result_image",
      "asset_role": "result_image",
      "asset_ref": "asset://A0123",
      "order": 2
    }
  ],
  "status": "active",
  "superseded_by": null,
  "created_at": "2026-07-17T00:00:00Z"
}
```

Rules:

- member keys are unique within a group;
- order values are unique positive integers;
- ordered group types require contiguous order starting at one;
- each member role must match the referenced AssetRecord role;
- category-bound members must match the group category;
- group type and member roles must satisfy the frozen registries;
- group members are long-lived material relationships, not current-Run scene
  outputs;
- one asset may belong to multiple groups;
- groups use the same active/superseded lifecycle and cannot be silently edited.

## 5. Cross-Boundary Validation

Validation is split deliberately:

### Contract validation

Pydantic validates shape, strict types, closed structural enums, reference syntax,
relative keys, local evidence/source invariants, uniqueness and lifecycle shape.

### Registry validation

`CapabilityRegistryHub` validates category, role, Claim, group type and configured
asset IDs against one frozen snapshot.

### Repository validation

Stage 3 validates referenced records exist, hashes match objects, supersede graphs
are acyclic and object metadata matches records.

### Selection and compiler validation

Stages 4 and 6 validate relationship completeness, derivation legality, current
Run dependencies and Claim visibility at word-level timing anchors.

No layer silently invents a replacement ID or changes evidence class to make an
invalid record pass.

## 6. Directory And Module Layout

```text
video_agent/contracts/v4/
  registry.py
  assets.py

video_agent/registries/
  contracts.py
  hub.py
  loaders.py
  freeze.py

config/registries/v4/
  category.json
  asset_role.json
  visual_structure.json
  operation_intent.json
  claim.json
  group_type.json
  configured_asset.json
```

Stage 2 converts the bootstrap registry into these typed source documents. Stage
1 consumes a reduced Agent-safe projection generated by the Hub. It does not read
a second hand-maintained registry.

The legacy `assets/catalog.json`, `_library_manifest.json`, relationship files,
derived registries and `assets/imports` are migration inputs only. Stage 2 does
not modify or delete them. Stage 3 owns the one-time import and cleanup decision.

## 7. Public API

```python
hub = CapabilityRegistryHub.load(repo_root / "config/registries/v4")
snapshot = hub.freeze(run_dir / "registry_snapshot.json")

record = AssetRecord.model_validate(payload)
validate_asset_against_registry(record, snapshot)

group = AssetGroup.model_validate(payload)
validate_group_against_assets(group, records, snapshot)
```

Stage 1 adapter functions continue to expose the exact minimal payload required
by Scope and Scene Semantics. They are projections from the frozen Hub snapshot,
not independent contracts.

## 8. Tests And Completion Definition

Stage 2 implementation is complete only when:

1. all registry documents load with strict Pydantic contracts;
2. duplicate IDs and normalized aliases fail;
3. disabled entries are excluded from new lookups but preserved in snapshots;
4. snapshot hashes are deterministic and content changes invalidate the hash;
5. Stage 1 prompts are generated from the new Hub snapshot and the Stage 0 real
   Scope/Scene run still validates;
6. AssetRecord enforces relative object keys, immutable-style identity, lifecycle,
   source/lineage and evidence/Claim invariants;
7. AssetGroup enforces member/order invariants and registry compatibility;
8. no V4 asset contract contains review/approval fields;
9. role and category fields remain dynamic strings validated at boundaries;
10. focused pytest and Ruff checks pass.

## 9. Stage 3 Handoff

Stage 3 must implement Repository, SQLite and ObjectStore using these contracts
without changing their semantics. Its migration must allocate stable sequential
references, normalize relative object keys, convert legacy provenance/evidence,
build relationship groups, mark imported records active and preserve a migration
ledger. It may not reintroduce legacy review status into V4.

## 10. Assumptions

1. The project remains single-brand: 柯幻熊猫. Brand identity does not need a
   cross-tenant dimension in this schema.
2. Media bytes remain under the repository-local asset tree in the first local
   ObjectStore implementation, while contracts use object keys so future OSS does
   not change semantic layers.
3. Sequential IDs are repository infrastructure, not semantic IDs and not model
   decisions.
4. Existing assets are not deleted in Stage 2. Ambiguous migration inputs are
   reported by Stage 3 instead of guessed here.
