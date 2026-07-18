from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_agent.ai.prompt_loader import LoadedPrompt, load_prompt
from video_agent.assets.v4.derivation_orchestrator import DerivationCapabilityBinding
from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4 import DerivationEntry
from video_agent.contracts.v4.resolved_assets import DerivationRequest
from video_agent.registries import CapabilityRegistryHub


@dataclass(frozen=True)
class ComposedDerivationPrompt:
    capability_id: str
    text: str
    template_path: str
    template_sha256: str
    input_sha256: str


def resolve_prompt_template_path(repo_root: Path, entry: DerivationEntry) -> Path | None:
    template = entry.capabilities.prompt_template
    if not template:
        return None
    path = Path(template)
    if not path.is_absolute():
        path = repo_root / path
    return path


def prompt_template_sha256(repo_root: Path, entry: DerivationEntry) -> str:
    path = resolve_prompt_template_path(repo_root, entry)
    if path is None:
        from hashlib import sha256

        return sha256(f"deterministic:{entry.id}:{entry.capabilities.version}".encode("utf-8")).hexdigest()
    if not path.is_file():
        raise Stage4Error(
            "prompt_contract_invalid",
            f"derivation prompt template missing: {entry.capabilities.prompt_template}",
        )
    return load_prompt(path).sha256


def compose_derivation_prompt(
    *,
    repo_root: Path,
    hub: CapabilityRegistryHub,
    request: DerivationRequest,
    binding: DerivationCapabilityBinding,
    parent_roles: list[str],
    member_key: str | None = None,
) -> ComposedDerivationPrompt:
    entry = hub.require_entry("derivation", binding.capability_id)
    if not isinstance(entry, DerivationEntry):
        raise Stage4Error(
            "missing_derivation_capability",
            f"derivation entry missing: {binding.capability_id}",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
    path = resolve_prompt_template_path(repo_root, entry)
    if path is None:
        raise Stage4Error(
            "prompt_contract_invalid",
            f"capability {binding.capability_id} has no prompt template",
            scene_id=request.scene_id,
            slot_id=request.slot_id,
        )
    loaded: LoadedPrompt = load_prompt(path)
    narrative = request.narrative_context
    narrative_block = "none"
    if narrative is not None:
        narrative_block = "\n".join(
            [
                f"scene_text: {narrative.scene_text}",
                f"anchor_phrase: {narrative.anchor_phrase}",
                f"previous_scene_summary: {narrative.previous_scene_summary or 'none'}",
                f"next_scene_summary: {narrative.next_scene_summary or 'none'}",
            ]
        )
    source_facts = "\n".join(
        [
            f"category_id: {request.category_id or 'none'}",
            f"parent_asset_refs: {', '.join(request.parent_asset_refs) or '[]'}",
            f"parent_roles: {', '.join(parent_roles) or '[]'}",
            f"context_asset_refs: {', '.join(request.context_asset_refs) or '[]'}",
            f"required_group: {request.required_group.pattern_id if request.required_group else 'none'}",
            f"member_key: {member_key or request.required_group.member_key if request.required_group else 'none'}",
            "parents=[]" if not request.parent_asset_refs else "parents=provided",
        ]
    )
    target_role = request.target_asset_role
    if request.required_group is not None and member_key is not None:
        pattern = hub.entry("relation_pattern", request.required_group.pattern_id)
        if pattern is not None:
            for member in getattr(pattern, "members", []):
                if member.member_key == member_key:
                    target_role = member.asset_role
                    break
    rendered = loaded.text.format(
        capability_id=binding.capability_id,
        target_asset_role=target_role,
        target_orientation=request.target_orientation or "unspecified",
        target_size=binding.target_size,
        source_facts=source_facts,
        narrative_context=narrative_block,
        required_changes=f"Produce asset role `{target_role}` for scene `{request.scene_id}` slot `{request.slot_id}`.",
        forbidden_changes="Do not change parent refs, category, evidence ceiling, or invent website UI facts.",
        output_geometry=(
            f"Fill the entire {binding.target_size} frame. "
            "No gray/dark presentation canvas, border, or caption unless the capability recipe requires one."
        ),
    )
    return ComposedDerivationPrompt(
        capability_id=binding.capability_id,
        text=rendered,
        template_path=path.relative_to(repo_root).as_posix() if path.is_relative_to(repo_root) else path.as_posix(),
        template_sha256=loaded.sha256,
        input_sha256=binding.prompt_input_sha256,
    )
