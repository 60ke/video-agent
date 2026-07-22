from __future__ import annotations

from pathlib import Path

from video_agent.assets.v4.derivation_orchestrator import DerivationCapabilityBinding
from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4 import DerivationEntry
from video_agent.contracts.v4.resolved_assets import DerivationRequest
from video_agent.derivation.v4.handler_fingerprint import handler_source_fingerprint
from video_agent.derivation.v4.prompt_composer import prompt_template_sha256
from video_agent.derivation.v4.sizing import target_size_for_orientation
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistryHub


class RegistryDerivationCapabilityResolver:
    """Stage 5 registry-backed capability binding for DerivationRequest shapes."""

    def __init__(self, hub: CapabilityRegistryHub, *, repo_root: Path | None = None) -> None:
        self.hub = hub
        self.repo_root = repo_root

    def resolve(self, request: DerivationRequest) -> DerivationCapabilityBinding:
        entry = self.hub.entry("derivation", request.derivation_type)
        if entry is None or not isinstance(entry, DerivationEntry):
            raise Stage4Error(
                "missing_derivation_capability",
                f"unknown or disabled derivation capability: {request.derivation_type}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        if not entry.enabled:
            raise Stage4Error(
                "capability_disabled",
                f"derivation capability disabled: {request.derivation_type}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        caps = entry.capabilities
        parent_count = len(request.parent_asset_refs)
        if parent_count < caps.minimum_parents:
            raise Stage4Error(
                "capability_not_applicable",
                f"{entry.id} requires at least {caps.minimum_parents} parents",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        if caps.maximum_parents is not None and parent_count > caps.maximum_parents:
            raise Stage4Error(
                "capability_not_applicable",
                f"{entry.id} allows at most {caps.maximum_parents} parents",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        if request.required_group is not None:
            if (
                caps.allowed_group_patterns
                and request.required_group.pattern_id not in caps.allowed_group_patterns
            ):
                raise Stage4Error(
                    "capability_not_applicable",
                    f"{entry.id} does not allow pattern {request.required_group.pattern_id}",
                    scene_id=request.scene_id,
                    slot_id=request.slot_id,
                )
        target_is_group_input = (
            request.required_group is not None
            and request.required_group.member_key == "source_result"
            and request.target_asset_role == "result_image"
            and request.target_asset_role in caps.input_roles
        )
        if request.target_asset_role not in caps.output_roles and not target_is_group_input:
            raise Stage4Error(
                "capability_not_applicable",
                f"{entry.id} cannot produce or reuse role {request.target_asset_role}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )
        if (
            request.target_orientation
            and request.target_orientation not in caps.supports_orientations
        ):
            raise Stage4Error(
                "capability_not_applicable",
                f"{entry.id} does not support orientation {request.target_orientation}",
                scene_id=request.scene_id,
                slot_id=request.slot_id,
            )

        if self.repo_root is not None:
            template_sha = prompt_template_sha256(self.repo_root, entry)
        else:
            from hashlib import sha256

            template_sha = (
                sha256(caps.prompt_template.encode("utf-8")).hexdigest()
                if caps.prompt_template
                else sha256(f"deterministic:{entry.id}:{caps.version}".encode("utf-8")).hexdigest()
            )
        prompt_input_sha256 = sha256_json(
            {
                "derivation_type": request.derivation_type,
                "category_id": request.category_id,
                "target_asset_role": request.target_asset_role,
                "required_group": request.required_group.model_dump(mode="json")
                if request.required_group
                else None,
                "narrative": request.narrative_context.model_dump(mode="json")
                if request.narrative_context
                else None,
                "target_orientation": request.target_orientation,
                "prompt_contract_version": caps.prompt_contract_version,
            }
        )
        target_size = target_size_for_orientation(request.target_orientation)
        handler_sha = handler_source_fingerprint(entry.handler)
        execution_fingerprint = sha256_json(
            {
                "capability_id": entry.id,
                "capability_version": caps.version,
                "executor_kind": caps.executor_kind,
                "provider_profile": caps.provider_profile,
                "prompt_template_sha256": template_sha,
                "website_truth_policy": caps.website_truth_policy,
                "target_size": target_size,
                "handler": entry.handler or "",
                "handler_source_sha256": handler_sha,
            }
        )
        provider_model = "pil" if caps.executor_kind == "deterministic" else "gpt-image-2"
        return DerivationCapabilityBinding(
            capability_id=entry.id,
            capability_version=caps.version,
            execution_fingerprint=execution_fingerprint,
            is_fake=False,
            provider_profile_id=caps.provider_profile or "deterministic",
            provider_model=provider_model,
            target_size=target_size,
            prompt_template_sha256=template_sha,
            prompt_input_sha256=prompt_input_sha256,
        )
