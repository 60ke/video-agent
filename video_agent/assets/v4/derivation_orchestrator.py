from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from PIL import Image

from video_agent.contracts.v4 import (
    AssetGroup,
    AssetGroupMember,
    AssetLineage,
    EvidenceClass,
    RelationPatternEntry,
    SourceKind,
)
from video_agent.contracts.v4.resolved_assets import DerivationRequest, RequiredGroupSpec
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistryHub

from .repository import AssetDraft, AssetGroupDraft, AssetResolutionSession, GroupQuery
from .stage4_errors import Stage4Error


@dataclass(frozen=True)
class DerivationCapabilityBinding:
    capability_id: str
    capability_version: str
    execution_fingerprint: str
    is_fake: bool = False
    provider_profile_id: str = "fake"
    provider_model: str = "fixture"
    target_size: str = "1024x1792"
    prompt_template_sha256: str = ""
    prompt_input_sha256: str = ""


@dataclass(frozen=True)
class PreparedDerivation:
    request_id: str
    capability_id: str
    capability_version: str
    ordered_parent_refs: tuple[str, ...]
    ordered_context_refs: tuple[str, ...]
    prompt_template_sha256: str
    prompt_input_sha256: str
    provider_profile_id: str
    provider_model: str
    target_size: str
    execution_fingerprint: str
    derivation_signature: str


@dataclass
class DerivationResultDraft:
    drafts: list[AssetDraft] = field(default_factory=list)
    draft_member_keys: list[str] = field(default_factory=list)
    reuse_member_refs: dict[str, str] = field(default_factory=dict)
    group_type: str | None = None
    pattern_id: str | None = None
    category_id: str | None = None


class DerivationCapabilityResolver(Protocol):
    def resolve(self, request: DerivationRequest) -> DerivationCapabilityBinding: ...


class DerivationExecutor(Protocol):
    def execute(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft: ...


class FakeCapabilityResolver:
    """Fixture-only resolver. Production Stage 5 must inject a registry-backed resolver."""

    def resolve(self, request: DerivationRequest) -> DerivationCapabilityBinding:
        fingerprint = sha256(f"fake:{request.derivation_type}:1".encode("utf-8")).hexdigest()
        return DerivationCapabilityBinding(
            capability_id=request.derivation_type,
            capability_version="1",
            execution_fingerprint=fingerprint,
            is_fake=True,
            provider_profile_id="fake",
            provider_model="fixture",
            target_size="1024x1792",
            prompt_template_sha256=sha256(b"fake-prompt-template").hexdigest(),
            prompt_input_sha256=fingerprint,
        )


class FakeDerivationExecutor:
    """Fixture executor: copy parent bytes into new object keys; can synthesize full groups."""

    def __init__(
        self,
        fixture_root: Path | None = None,
        registry: CapabilityRegistryHub | None = None,
    ) -> None:
        self.fixture_root = fixture_root
        self.registry = registry

    def execute(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft:
        if request.required_group is not None:
            return self._execute_group(request, binding, prepared, session)
        return self._execute_single(request, binding, prepared, session)

    def _execute_single(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft:
        if request.parent_asset_refs:
            parent = self._require_parent(request, session)
            draft = self._draft_from_parent(
                request=request,
                binding=binding,
                session=session,
                parent=parent,
                role=request.target_asset_role,
                member_key=request.slot_id,
                signature=prepared.derivation_signature,
            )
        else:
            draft = self._draft_without_parent(
                request=request,
                binding=binding,
                prepared=prepared,
                session=session,
            )
        return DerivationResultDraft(drafts=[draft], draft_member_keys=[request.slot_id])

    def _execute_group(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> DerivationResultDraft:
        if self.registry is None:
            raise Stage4Error(
                "derivation_failed",
                "fake group derivation requires registry",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        assert request.required_group is not None
        pattern = self.registry.entry("relation_pattern", request.required_group.pattern_id)
        if not isinstance(pattern, RelationPatternEntry):
            raise Stage4Error(
                "derivation_failed",
                f"unknown relation pattern: {request.required_group.pattern_id}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        parent = self._require_parent(request, session)
        reuse: dict[str, str] = {}
        drafts: list[AssetDraft] = []
        draft_keys: list[str] = []
        for member in sorted(pattern.members, key=lambda item: item.order):
            if _should_reuse_parent(
                request.required_group.pattern_id,
                member.member_key,
                member.asset_role,
                parent.asset_role,
            ):
                reuse[member.member_key] = parent.asset_ref
                continue
            signature = build_derivation_signature(
                parent_refs=list(request.parent_asset_refs),
                parent_hashes=[parent.content_sha256],
                context_refs=list(request.context_asset_refs),
                context_hashes=_content_hashes(session, request.context_asset_refs),
                category_id=request.category_id,
                role=member.asset_role,
                pattern_id=request.required_group.pattern_id,
                member_key=member.member_key,
                capability_id=binding.capability_id,
                capability_version=binding.capability_version,
                execution_fingerprint=binding.execution_fingerprint,
                narrative_fingerprint=sha256(
                    f"{request.scene_id}|{request.slot_id}".encode("utf-8")
                ).hexdigest(),
                target_orientation=request.target_orientation or "",
            )
            existing = session.find_by_derivation_signature(signature)
            if existing is not None:
                reuse[member.member_key] = existing.asset_ref
                continue
            drafts.append(
                self._draft_from_parent(
                    request=request,
                    binding=binding,
                    session=session,
                    parent=parent,
                    role=member.asset_role,
                    member_key=member.member_key,
                    signature=signature,
                )
            )
            draft_keys.append(member.member_key)
        return DerivationResultDraft(
            drafts=drafts,
            draft_member_keys=draft_keys,
            reuse_member_refs=reuse,
            group_type=request.required_group.group_type,
            pattern_id=request.required_group.pattern_id,
            category_id=request.category_id or parent.category_id,
        )

    def _require_parent(self, request: DerivationRequest, session: AssetResolutionSession):
        if not request.parent_asset_refs:
            raise Stage4Error(
                "derivation_failed",
                "fake derivation requires parent_asset_refs",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        parent = session.get_asset(request.parent_asset_refs[0])
        if parent is None:
            raise Stage4Error(
                "derivation_failed",
                f"parent missing: {request.parent_asset_refs[0]}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        return parent

    def _draft_from_parent(
        self,
        *,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        session: AssetResolutionSession,
        parent,
        role: str,
        member_key: str,
        signature: str,
    ) -> AssetDraft:
        now = datetime.now(timezone.utc)
        object_store = getattr(session.repository, "object_store", None)
        if object_store is None:
            raise Stage4Error(
                "derivation_failed",
                "repository has no object_store",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        source_path = object_store.resolve(parent.object_key)
        object_key = f"derived/stage4/{signature}_{member_key}.png"
        info = object_store.put_file(source_path, object_key)
        website_roles = {"parameter_panel", "feature_entry", "site_home"}
        evidence = EvidenceClass.FAITHFUL if role in website_roles else EvidenceClass.SEMANTIC
        return AssetDraft(
            filename=Path(info.object_key).name,
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=parent.module,
            category_id=request.category_id or parent.category_id,
            category_path=list(parent.category_path),
            asset_role=role,
            case_label=parent.case_label,
            industry=parent.industry,
            description=f"fake derived {member_key}",
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=False,
            source_kind=SourceKind.DERIVED,
            origin_type="stage4_fake",
            evidence_class=evidence,
            claims=list(parent.claims) if evidence == EvidenceClass.FAITHFUL else [],
            lineage=AssetLineage(
                parent_asset_refs=list(request.parent_asset_refs),
                derivation_type=request.derivation_type,
                executor_id=binding.capability_id,
                provider="fake",
                model="fixture",
                prompt_template_version=binding.capability_version,
                prompt_sha256=sha256(b"fake-prompt").hexdigest(),
                parameters_sha256=sha256(signature.encode("utf-8")).hexdigest(),
                derivation_signature=signature,
                created_at=now,
            ),
        )

    def _draft_without_parent(
        self,
        *,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ) -> AssetDraft:
        object_store = getattr(session.repository, "object_store", None)
        if object_store is None:
            raise Stage4Error(
                "derivation_failed",
                "repository has no object_store",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        digest = bytes.fromhex(prepared.derivation_signature)
        orientation = request.target_orientation or "landscape"
        width, height = (16, 9) if orientation == "landscape" else (9, 16) if orientation == "portrait" else (12, 12)
        color = tuple(48 + (value % 160) for value in digest[:3])
        object_key = f"derived/stage4/{prepared.derivation_signature}_{request.slot_id}.png"
        with NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            Image.new("RGB", (width, height), color).save(temporary)
            info = object_store.put_file(temporary, object_key)
        finally:
            temporary.unlink(missing_ok=True)
        category_parts = (request.category_id or "").split("/")
        now = datetime.now(timezone.utc)
        return AssetDraft(
            filename=Path(info.object_key).name,
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=category_parts[0] if len(category_parts) > 1 else None,
            category_id=request.category_id,
            category_path=category_parts[1:] if len(category_parts) > 1 else [],
            asset_role=request.target_asset_role,
            description=f"fake derived {request.target_asset_role}",
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=False,
            source_kind=SourceKind.DERIVED,
            origin_type="stage4_fake",
            evidence_class=EvidenceClass.SEMANTIC,
            claims=[],
            lineage=AssetLineage(
                parent_asset_refs=[],
                derivation_type=request.derivation_type,
                executor_id=binding.capability_id,
                provider="fake",
                model="fixture",
                prompt_template_version=binding.capability_version,
                prompt_sha256=binding.execution_fingerprint,
                parameters_sha256=sha256(prepared.derivation_signature.encode("utf-8")).hexdigest(),
                derivation_signature=prepared.derivation_signature,
                created_at=now,
            ),
        )


def _should_reuse_parent(pattern_id: str, member_key: str, member_role: str, parent_role: str) -> bool:
    if pattern_id == "editor_sequence" and member_key == "source_result" and parent_role == "result_image":
        return True
    if pattern_id == "reference_result_plan" and member_key == "result_image" and parent_role == "result_image":
        return True
    if pattern_id == "parameter_callout_sequence" and member_key == "base" and parent_role == "parameter_panel":
        return True
    return member_role == parent_role and member_key in {"source_result", "result_image", "base"}


def _content_hashes(session: AssetResolutionSession, refs: list[str]) -> list[str]:
    hashes: list[str] = []
    for ref in refs:
        asset = session.get_asset(ref)
        if asset is None:
            raise Stage4Error("derivation_failed", f"asset missing for signature: {ref}")
        hashes.append(asset.content_sha256)
    return hashes


def infer_derivation_type(
    *,
    asset_role: str,
    pattern_id: str | None,
    parent_asset_refs: list[str],
    scene_id: str | None = None,
    slot_id: str | None = None,
) -> str:
    """Map Stage 4 gap/relation shape to a Derivation Registry entry ID (no alias table)."""
    if pattern_id == "editor_sequence":
        return "result_to_editor_process"
    if pattern_id == "parameter_callout_sequence":
        return "site_params_flower_text_frame_sequence"
    if pattern_id == "reference_result_plan":
        if asset_role == "reference_image":
            return "result_to_reference_mock"
        if asset_role == "result_image":
            return "reference_to_result"
        if asset_role == "flat_plan":
            return "result_to_flat_plan"
        raise Stage4Error(
            "missing_derivation_capability",
            f"no derivation_type for reference_result_plan role={asset_role}",
            scene_id=scene_id,
            slot_id=slot_id,
        )
    if asset_role == "feature_entry":
        return "site_feature_entry_callout_keyframe"
    if asset_role in {"site_home", "parameter_panel"}:
        return "site_faithful_reframe"
    if asset_role == "edited_result":
        return "result_to_edited_result"
    if asset_role == "result_image" and not parent_asset_refs:
        return "text_to_result"
    if asset_role == "result_image" and parent_asset_refs:
        return "normalize_gallery_asset"
    raise Stage4Error(
        "missing_derivation_capability",
        f"no derivation_type for role={asset_role} pattern={pattern_id}",
        scene_id=scene_id,
        slot_id=slot_id,
    )


def build_derivation_signature(
    *,
    parent_refs: list[str],
    parent_hashes: list[str],
    category_id: str | None,
    role: str,
    pattern_id: str | None,
    member_key: str | None,
    capability_id: str,
    capability_version: str,
    execution_fingerprint: str,
    narrative_fingerprint: str = "",
    target_orientation: str = "",
    context_refs: list[str] | None = None,
    context_hashes: list[str] | None = None,
) -> str:
    payload = "|".join(
        [
            ",".join(parent_refs),
            ",".join(parent_hashes),
            ",".join(context_refs or []),
            ",".join(context_hashes or []),
            category_id or "",
            role,
            pattern_id or "",
            member_key or "",
            capability_id,
            capability_version,
            execution_fingerprint,
            narrative_fingerprint,
            target_orientation,
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def prepare_derivation(
    request: DerivationRequest,
    binding: DerivationCapabilityBinding,
    session: AssetResolutionSession,
) -> PreparedDerivation:
    """Stage 5 prepare step: bind capability fingerprints and own the final signature."""
    parent_hashes = _content_hashes(session, list(request.parent_asset_refs))
    context_hashes = _content_hashes(session, list(request.context_asset_refs))
    pattern_id = request.required_group.pattern_id if request.required_group else None
    member_key = request.required_group.member_key if request.required_group else None
    if request.narrative_context is None:
        narrative_fingerprint = ""
    else:
        narrative_fingerprint = sha256_json(request.narrative_context.model_dump(mode="json"))
    prompt_template_sha256 = binding.prompt_template_sha256 or sha256(
        f"template:{binding.capability_id}:{binding.capability_version}".encode("utf-8")
    ).hexdigest()
    prompt_input_sha256 = binding.prompt_input_sha256 or sha256_json(
        {
            "derivation_type": request.derivation_type,
            "category_id": request.category_id,
            "target_asset_role": request.target_asset_role,
            "narrative": request.narrative_context.model_dump(mode="json") if request.narrative_context else None,
            "target_orientation": request.target_orientation,
        }
    )
    signature = build_derivation_signature(
        parent_refs=list(request.parent_asset_refs),
        parent_hashes=parent_hashes,
        context_refs=list(request.context_asset_refs),
        context_hashes=context_hashes,
        category_id=request.category_id,
        role=request.target_asset_role,
        pattern_id=pattern_id,
        member_key=member_key,
        capability_id=binding.capability_id,
        capability_version=binding.capability_version,
        execution_fingerprint=binding.execution_fingerprint,
        narrative_fingerprint=narrative_fingerprint,
        target_orientation=request.target_orientation or "",
    )
    # Fold prompt/provider into the final owned signature so template/model changes invalidate reuse.
    signature = sha256(
        "|".join(
            [
                signature,
                prompt_template_sha256,
                prompt_input_sha256,
                binding.provider_profile_id,
                binding.provider_model,
                binding.target_size,
            ]
        ).encode("utf-8")
    ).hexdigest()
    return PreparedDerivation(
        request_id=request.request_id,
        capability_id=binding.capability_id,
        capability_version=binding.capability_version,
        ordered_parent_refs=tuple(request.parent_asset_refs),
        ordered_context_refs=tuple(request.context_asset_refs),
        prompt_template_sha256=prompt_template_sha256,
        prompt_input_sha256=prompt_input_sha256,
        provider_profile_id=binding.provider_profile_id,
        provider_model=binding.provider_model,
        target_size=binding.target_size,
        execution_fingerprint=binding.execution_fingerprint,
        derivation_signature=signature,
    )


def fulfill_derivation(
    request: DerivationRequest,
    *,
    session: AssetResolutionSession,
    resolver: DerivationCapabilityResolver,
    executor: DerivationExecutor,
    allow_fake: bool,
    requires_stage5: bool,
    registry: CapabilityRegistryHub | None = None,
) -> tuple[DerivationRequest, PreparedDerivation, AssetGroup | None]:
    binding = resolver.resolve(request)
    if binding.is_fake and requires_stage5 and not allow_fake:
        raise Stage4Error(
            "missing_derivation_capability",
            "fake derivation binding cannot enter production path",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
    if isinstance(executor, FakeDerivationExecutor) and requires_stage5 and not allow_fake:
        raise Stage4Error(
            "fake_executor_forbidden",
            "fake derivation executor cannot enter production path",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )

    prepared = prepare_derivation(request, binding, session)

    if request.required_group is None:
        existing = session.find_by_derivation_signature(prepared.derivation_signature)
        if existing is not None:
            request.status = "signature_hit"
            return request, prepared, None
        draft_result = executor.execute(request, binding, prepared, session)
        request.status = "generated"
        for draft in draft_result.drafts:
            session.register_asset(draft)
        request.status = "registered"
        return request, prepared, None

    parent_ref = request.parent_asset_refs[0]
    existing_groups = session.query_groups(
        GroupQuery(
            group_types=(request.required_group.group_type,),
            pattern_ids=(request.required_group.pattern_id,),
            category_ids=(request.category_id,) if request.category_id else (),
            containing_asset_refs=(parent_ref,),
            required_member_keys=(request.required_group.member_key,),
            active_only=True,
        )
    )
    if existing_groups:
        request.status = "signature_hit"
        return request, prepared, existing_groups[0]

    if registry is None:
        raise Stage4Error(
            "derivation_failed",
            "group derivation requires registry",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
    pattern = registry.entry("relation_pattern", request.required_group.pattern_id)
    if not isinstance(pattern, RelationPatternEntry):
        raise Stage4Error(
            "derivation_failed",
            f"unknown relation pattern: {request.required_group.pattern_id}",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )

    draft_result = executor.execute(request, binding, prepared, session)
    request.status = "generated"
    member_refs = dict(draft_result.reuse_member_refs)
    for member_key, draft in zip(draft_result.draft_member_keys, draft_result.drafts, strict=True):
        member_refs[member_key] = session.register_asset(draft).asset_ref
    members = [
        AssetGroupMember(
            member_key=member.member_key,
            asset_role=member.asset_role,
            asset_ref=member_refs[member.member_key],
            order=member.order,
        )
        for member in sorted(pattern.members, key=lambda item: item.order)
    ]
    group = session.register_group(
        AssetGroupDraft(
            group_type=request.required_group.group_type,
            pattern_id=request.required_group.pattern_id,
            category_id=request.category_id or draft_result.category_id or "",
            members=members,
        )
    )
    request.status = "registered"
    return request, prepared, group


def required_group_spec(group_type: str, pattern_id: str, member_key: str) -> RequiredGroupSpec:
    return RequiredGroupSpec(group_type=group_type, pattern_id=pattern_id, member_key=member_key)
