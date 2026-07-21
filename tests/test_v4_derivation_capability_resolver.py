from __future__ import annotations

from pathlib import Path

import pytest

from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4.resolved_assets import DerivationRequest, RequiredGroupSpec
from video_agent.derivation.v4 import RegistryDerivationCapabilityResolver
from video_agent.registries import CapabilityRegistryHub


REGISTRY_ROOT = Path(__file__).parents[1] / "config" / "registries" / "v4"


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(REGISTRY_ROOT)


def test_registry_resolver_binds_derivation_type(hub: CapabilityRegistryHub) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub)
    binding = resolver.resolve(
        DerivationRequest(
            request_id="derivation://R0001",
            scene_id="s001",
            slot_id="result",
            derivation_type="text_to_result",
            category_id="文生图/文化墙",
            target_asset_role="result_image",
            evidence_ceiling="E2_semantic_derivative",
        )
    )
    assert binding.capability_id == "text_to_result"
    assert binding.capability_version == "1"
    assert binding.is_fake is False
    assert binding.prompt_template_sha256
    assert binding.execution_fingerprint


def test_registry_resolver_rejects_parent_mismatch(hub: CapabilityRegistryHub) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub)
    with pytest.raises(Stage4Error) as exc:
        resolver.resolve(
            DerivationRequest(
                request_id="derivation://R0002",
                scene_id="s001",
                slot_id="result",
                derivation_type="text_to_result",
                target_asset_role="result_image",
                parent_asset_refs=["asset://A0001"],
                evidence_ceiling="E2_semantic_derivative",
            )
        )
    assert exc.value.code == "capability_not_applicable"


def test_registry_resolver_accepts_reused_input_member_for_group_derivation(
    hub: CapabilityRegistryHub,
) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub)
    binding = resolver.resolve(
        DerivationRequest(
            request_id="derivation://R0003",
            scene_id="s006",
            slot_id="source_result",
            derivation_type="result_to_editor_process",
            category_id="文生图/文化墙",
            target_asset_role="result_image",
            required_group=RequiredGroupSpec(
                group_type="process",
                pattern_id="editor_sequence",
                member_key="source_result",
            ),
            parent_asset_refs=["asset://A0001"],
            evidence_ceiling="E2_semantic_derivative",
        )
    )
    assert binding.capability_id == "result_to_editor_process"
