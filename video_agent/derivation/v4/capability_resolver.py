from __future__ import annotations

from hashlib import sha256

from video_agent.assets.v4.derivation_orchestrator import DerivationCapabilityBinding
from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4 import DerivationEntry
from video_agent.contracts.v4.resolved_assets import DerivationRequest
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistryHub


class RegistryDerivationCapabilityResolver:
    """Stage 5 registry-backed capability binding for DerivationRequest shapes."""

    def __init__(self, hub: CapabilityRegistryHub) -> None:
        self.hub = hub

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
        if request.target_asset_role not in caps.output_roles:
            raise Stage4Error(
                "capability_not_applicable",
                f"{entry.id} cannot produce role {request.target_asset_role}",
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

        prompt_template_sha256 = (
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
        execution_fingerprint = sha256_json(
            {
                "capability_id": entry.id,
                "capability_version": caps.version,
                "executor_kind": caps.executor_kind,
                "provider_profile": caps.provider_profile,
                "prompt_template_sha256": prompt_template_sha256,
                "website_truth_policy": caps.website_truth_policy,
            }
        )
        return DerivationCapabilityBinding(
            capability_id=entry.id,
            capability_version=caps.version,
            execution_fingerprint=execution_fingerprint,
            is_fake=False,
            provider_profile_id=caps.provider_profile or "deterministic",
            provider_model=caps.executor_kind,
            target_size="1024x1792",
            prompt_template_sha256=prompt_template_sha256,
            prompt_input_sha256=prompt_input_sha256,
        )
