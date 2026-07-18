from __future__ import annotations

from collections.abc import Mapping

from video_agent.contracts.v4 import (
    AssetGroup,
    AssetRecord,
    AssetRoleEntry,
    DomainValidationError,
    FrozenRegistrySnapshot,
    GroupTypeEntry,
    ValidationIssue,
)
from video_agent.registries import CapabilityRegistryHub


def _hub(value: CapabilityRegistryHub | FrozenRegistrySnapshot) -> CapabilityRegistryHub:
    return value if isinstance(value, CapabilityRegistryHub) else CapabilityRegistryHub.from_snapshot(value)


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, message=message)


def validate_asset_against_registry(
    asset: AssetRecord,
    registry: CapabilityRegistryHub | FrozenRegistrySnapshot,
) -> None:
    hub = _hub(registry)
    issues: list[ValidationIssue] = []
    role = hub.entry("asset_role", asset.asset_role)
    if not isinstance(role, AssetRoleEntry):
        issues.append(_issue("unknown_asset_role", "asset_role", f"unknown or disabled role: {asset.asset_role}"))
    else:
        if asset.source_kind not in role.allowed_source_kinds:
            issues.append(
                _issue(
                    "source_kind_not_allowed",
                    "source_kind",
                    f"{asset.source_kind.value} is not allowed for role {asset.asset_role}",
                )
            )
        if role.requires_category and asset.category_id is None:
            issues.append(_issue("category_required", "category_id", f"role requires category: {asset.asset_role}"))

    if asset.category_id is not None and hub.entry("category", asset.category_id) is None:
        issues.append(
            _issue("unknown_category", "category_id", f"unknown or disabled category: {asset.category_id}")
        )

    for index, claim_id in enumerate(asset.claims):
        claim = hub.entry("claim", claim_id)
        if claim is None:
            issues.append(_issue("unknown_claim", f"claims[{index}]", f"unknown or disabled claim: {claim_id}"))
            continue
        required = getattr(claim, "required_evidence_classes", [])
        if asset.evidence_class not in required:
            issues.append(
                _issue(
                    "insufficient_evidence",
                    f"claims[{index}]",
                    f"{asset.evidence_class.value} cannot support claim {claim_id}",
                )
            )
    if issues:
        raise DomainValidationError("AssetRecord", issues)


def validate_group_against_assets(
    group: AssetGroup,
    assets: Mapping[str, AssetRecord],
    registry: CapabilityRegistryHub | FrozenRegistrySnapshot,
) -> None:
    hub = _hub(registry)
    issues: list[ValidationIssue] = []
    group_type = hub.entry("group_type", group.group_type)
    if not isinstance(group_type, GroupTypeEntry):
        issues.append(
            _issue("unknown_group_type", "group_type", f"unknown or disabled group type: {group.group_type}")
        )
    if hub.entry("category", group.category_id) is None:
        issues.append(
            _issue("unknown_category", "category_id", f"unknown or disabled category: {group.category_id}")
        )

    if isinstance(group_type, GroupTypeEntry) and group_type.ordered:
        orders = sorted(member.order for member in group.members)
        expected = list(range(1, len(group.members) + 1))
        if orders != expected:
            issues.append(_issue("non_contiguous_order", "members", f"ordered group requires {expected}, got {orders}"))

    for index, member in enumerate(group.members):
        path = f"members[{index}]"
        asset = assets.get(member.asset_ref)
        if asset is None:
            issues.append(_issue("missing_asset", f"{path}.asset_ref", f"asset does not exist: {member.asset_ref}"))
            continue
        if asset.asset_role != member.asset_role:
            issues.append(
                _issue(
                    "member_role_mismatch",
                    f"{path}.asset_role",
                    f"member says {member.asset_role}, asset says {asset.asset_role}",
                )
            )
        if asset.category_id is not None and asset.category_id != group.category_id:
            issues.append(
                _issue(
                    "member_category_mismatch",
                    f"{path}.asset_ref",
                    f"asset category {asset.category_id} differs from group {group.category_id}",
                )
            )
        role = hub.entry("asset_role", member.asset_role)
        if not isinstance(role, AssetRoleEntry):
            issues.append(
                _issue("unknown_asset_role", f"{path}.asset_role", f"unknown or disabled role: {member.asset_role}")
            )
        elif group.group_type not in role.allowed_group_types:
            issues.append(
                _issue(
                    "role_not_allowed_in_group",
                    f"{path}.asset_role",
                    f"role {member.asset_role} does not allow {group.group_type}",
                )
            )
        if (
            isinstance(group_type, GroupTypeEntry)
            and group_type.allowed_member_roles
            and member.asset_role not in group_type.allowed_member_roles
        ):
            issues.append(
                _issue(
                    "group_member_role_not_allowed",
                    f"{path}.asset_role",
                    f"group type {group.group_type} does not allow {member.asset_role}",
                )
            )
    if issues:
        raise DomainValidationError("AssetGroup", issues)
