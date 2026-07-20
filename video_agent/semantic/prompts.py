from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_agent.ai.prompt_loader import load_prompt
from video_agent.io import load_json, sha256_json


@dataclass(frozen=True)
class PromptBundle:
    capability: str
    version: str
    system_prompt: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    component_fingerprints: dict[str, str]

    @property
    def fingerprint(self) -> str:
        return sha256_json(
            {
                "capability": self.capability,
                "version": self.version,
                "system_prompt": self.system_prompt,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "components": self.component_fingerprints,
            }
        )


def _prompt_root(repo_root: Path, capability: str) -> Path:
    return repo_root / "video_agent" / "prompts" / "v4" / capability


def load_scope_prompt(repo_root: Path) -> PromptBundle:
    root = _prompt_root(repo_root, "scope_classifier")
    system = load_prompt(root / "system.v1.md")
    examples = load_json(root / "examples.v1.json")
    return PromptBundle(
        capability="scope_classifier",
        version="scope_classifier.v1",
        system_prompt=system.text + "\n\n# Examples\n" + json.dumps(examples, ensure_ascii=False, indent=2),
        input_schema=load_json(root / "input.schema.json"),
        output_schema=load_json(root / "output.schema.json"),
        component_fingerprints={"system": system.sha256, "examples": sha256_json(examples)},
    )


def load_goal_narration_prompt(repo_root: Path) -> PromptBundle:
    root = _prompt_root(repo_root, "goal_narration")
    system = load_prompt(root / "system.v1.md")
    examples = load_json(root / "examples.v1.json")
    return PromptBundle(
        capability="goal_narration",
        version="goal_narration.v1",
        system_prompt=system.text + "\n\n# Examples\n" + json.dumps(examples, ensure_ascii=False, indent=2),
        input_schema=load_json(root / "input.schema.json"),
        output_schema=load_json(root / "output.schema.json"),
        component_fingerprints={"system": system.sha256, "examples": sha256_json(examples)},
    )


def load_scene_prompt(repo_root: Path, registry_payload: dict[str, Any]) -> PromptBundle:
    root = _prompt_root(repo_root, "scene_semantics")
    system = load_prompt(root / "system.v1.md")
    decision_table = load_prompt(root / "decision_table.v1.md")
    examples = load_json(root / "examples.v1.json")
    rendered = (
        system.text.replace("{{DECISION_TABLE}}", decision_table.text.strip())
        .replace("{{REGISTRY_SNAPSHOT}}", json.dumps(registry_payload, ensure_ascii=False, indent=2))
        .replace("{{POSITIVE_EXAMPLES}}", json.dumps(examples.get("positive", []), ensure_ascii=False, indent=2))
        .replace("{{NEGATIVE_EXAMPLES}}", json.dumps(examples.get("negative", []), ensure_ascii=False, indent=2))
    )
    return PromptBundle(
        capability="scene_semantics",
        version="scene_semantics.v1",
        system_prompt=rendered,
        input_schema=load_json(root / "input.schema.json"),
        output_schema=load_json(root / "output.schema.json"),
        component_fingerprints={
            "system": system.sha256,
            "decision_table": decision_table.sha256,
            "examples": sha256_json(examples),
            "registry": sha256_json(registry_payload),
        },
    )


def load_field_repair_prompt(repo_root: Path) -> PromptBundle:
    root = _prompt_root(repo_root, "field_repair")
    system = load_prompt(root / "system.v1.md")
    return PromptBundle(
        capability="field_repair",
        version="field_repair.v1",
        system_prompt=system.text,
        input_schema=load_json(root / "input.schema.json"),
        output_schema=load_json(root / "output.schema.json"),
        component_fingerprints={"system": system.sha256},
    )
