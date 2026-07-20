from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import V4Contract


_SHA256_PATTERN = r"^[a-f0-9]{64}$"
_CASE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]+$"
_RUN_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]+$"
_OFFICIAL_BRAND_LOGO = "assets/brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png"

ProductionNodeId = Literal[
    "narration",
    "registry_voice",
    "speech",
    "scope",
    "scene",
    "assets",
    "anchor",
    "motion_audio",
    "bgm",
    "compile",
    "structured_qa",
    "render",
    "cover",
    "delivery_qa",
    "finalize",
]

PRODUCTION_DAG_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "narration": (),
    "registry_voice": ("narration",),
    "speech": ("registry_voice",),
    "scope": ("narration",),
    "scene": ("narration", "registry_voice", "scope"),
    "assets": ("scene",),
    "anchor": ("speech", "scene"),
    "motion_audio": ("assets", "anchor"),
    "bgm": ("registry_voice",),
    "compile": ("motion_audio", "bgm", "assets", "anchor"),
    "structured_qa": ("compile",),
    "render": ("structured_qa",),
    "cover": ("assets", "scope", "narration"),
    "delivery_qa": ("render", "cover"),
    "finalize": ("delivery_qa",),
}


def _relative_object_key(value: str) -> str:
    if not value or value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("object_key must be a non-empty relative POSIX path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise ValueError("object_key must be normalized and cannot traverse or name a drive")
    return value


class GoalNarrationResponse(V4Contract):
    schema_version: Literal["v4.goal_narration.1"]
    spoken_text: str = Field(min_length=1)
    language: Literal["zh-CN"]

    @field_validator("spoken_text")
    @classmethod
    def validate_spoken_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("spoken_text cannot be blank")
        if "```" in text or any(line.lstrip().startswith("# ") for line in text.splitlines()):
            raise ValueError("spoken_text cannot contain Markdown")
        return text


class ProductionBgmConfig(V4Contract):
    enabled: bool = False
    profile_id: str | None = None

    @model_validator(mode="after")
    def validate_enabled_profile(self) -> "ProductionBgmConfig":
        if self.enabled and not self.profile_id:
            raise ValueError("enabled BGM requires profile_id")
        return self


class ProductionCoverConfig(V4Contract):
    enabled: bool = True


class ProductionOutroConfig(V4Contract):
    enabled: bool = True
    configured_asset_key: Literal["default_outro"] = "default_outro"


class ProductionRenderConfig(V4Contract):
    quality: Literal["draft", "final"] = "final"
    postroll_frames: int = Field(default=0, ge=0)


class V4ProductionCase(V4Contract):
    schema_version: Literal[4] = 4
    case_id: str = Field(pattern=_CASE_ID_PATTERN)
    input_mode: Literal["script", "goal"]
    goal: str | None = None
    script_object_key: str | None = None
    platform_profile_id: Literal["douyin_portrait_v1"] = "douyin_portrait_v1"
    voice_profile_id: str = "minimax_adman_clear_01"
    sfx_profile_id: str = "normal"
    bgm: ProductionBgmConfig = Field(default_factory=ProductionBgmConfig)
    random_seed: str = Field(min_length=1)
    cover: ProductionCoverConfig = Field(default_factory=ProductionCoverConfig)
    outro: ProductionOutroConfig = Field(default_factory=ProductionOutroConfig)
    render: ProductionRenderConfig = Field(default_factory=ProductionRenderConfig)

    @field_validator("script_object_key")
    @classmethod
    def validate_script_key(cls, value: str | None) -> str | None:
        return None if value is None else _relative_object_key(value)

    @model_validator(mode="after")
    def validate_input_mode(self) -> "V4ProductionCase":
        if self.input_mode == "script":
            if self.script_object_key is None:
                raise ValueError("script mode requires script_object_key")
            if self.goal is not None:
                raise ValueError("script mode cannot set goal")
        else:
            if self.goal is None or not self.goal.strip():
                raise ValueError("goal mode requires a non-empty goal")
            if self.script_object_key is not None:
                raise ValueError("goal mode cannot set script_object_key")
        return self


class BgmDuckingConfig(V4Contract):
    threshold: float = Field(gt=0, le=1)
    ratio: float = Field(ge=1)
    attack_ms: int = Field(ge=0)
    release_ms: int = Field(ge=0)


class BgmProfile(V4Contract):
    schema_version: Literal["v4.bgm_profile.1"] = "v4.bgm_profile.1"
    profile_id: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    sample_rate_hz: Literal[48000] = 48000
    channels: Literal[2] = 2
    gain_db: float
    loop: bool = True
    duck_under_voice: bool = True
    ducking: BgmDuckingConfig

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        return _relative_object_key(value)


class BgmPlan(V4Contract):
    schema_version: Literal["v4.bgm_plan.1"] = "v4.bgm_plan.1"
    profile_id: str = Field(min_length=1)
    profile_content_sha256: str = Field(pattern=_SHA256_PATTERN)
    object_key: str = Field(min_length=1)
    media_content_sha256: str = Field(pattern=_SHA256_PATTERN)
    gain_db: float
    loop: bool
    duck_under_voice: bool
    ducking: BgmDuckingConfig

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        return _relative_object_key(value)


class CoverBrief(V4Contract):
    schema_version: Literal["v4.cover_brief.1"] = "v4.cover_brief.1"
    narration_sha256: str = Field(pattern=_SHA256_PATTERN)
    video_scope_sha256: str = Field(pattern=_SHA256_PATTERN)
    full_narration_text: str = Field(min_length=1)
    title: str = Field(min_length=1)
    subtitle: str | None = None
    representative_asset_refs: list[str] = Field(default_factory=list)
    brand_logo_object_key: Literal[_OFFICIAL_BRAND_LOGO] = _OFFICIAL_BRAND_LOGO
    platform_profile_id: Literal["douyin_portrait_v1"] = "douyin_portrait_v1"

    @field_validator("representative_asset_refs")
    @classmethod
    def validate_asset_refs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("representative_asset_refs must be unique")
        if any(not value.startswith("asset://A") for value in values):
            raise ValueError("representative assets must use asset://A references")
        return values


class QaCheck(V4Contract):
    check_id: str = Field(min_length=1)
    status: Literal["pass", "warning", "fail"]
    hard: bool = True
    message: str = Field(min_length=1)
    artifact_refs: list[str] = Field(default_factory=list)


class StructuredQaReport(V4Contract):
    schema_version: Literal["v4.structured_qa.1"] = "v4.structured_qa.1"
    timeline_sha256: str = Field(pattern=_SHA256_PATTERN)
    passed: bool
    checks: list[QaCheck] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_passed(self) -> "StructuredQaReport":
        expected = not any(check.hard and check.status == "fail" for check in self.checks)
        if self.passed != expected:
            raise ValueError("passed must reflect all hard checks")
        return self


class DeliveryQaReport(V4Contract):
    schema_version: Literal["v4.delivery_qa.1"] = "v4.delivery_qa.1"
    video_object_key: str = Field(min_length=1)
    cover_object_key: str = Field(min_length=1)
    passed: bool
    checks: list[QaCheck] = Field(min_length=1)

    @field_validator("video_object_key", "cover_object_key")
    @classmethod
    def validate_object_keys(cls, value: str) -> str:
        return _relative_object_key(value)

    @model_validator(mode="after")
    def validate_passed(self) -> "DeliveryQaReport":
        expected = not any(check.hard and check.status == "fail" for check in self.checks)
        if self.passed != expected:
            raise ValueError("passed must reflect all hard checks")
        return self


class ProductionArtifact(V4Contract):
    object_key: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        return _relative_object_key(value)


class ProductionNodeManifest(V4Contract):
    node_id: ProductionNodeId
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    dependency_node_ids: list[ProductionNodeId] = Field(default_factory=list)
    input_fingerprints: dict[str, str] = Field(default_factory=dict)
    outputs: list[ProductionArtifact] = Field(default_factory=list)
    elapsed_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None

    @field_validator("dependency_node_ids")
    @classmethod
    def validate_dependencies(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("dependency_node_ids must be unique")
        return values


class V4RunManifest(V4Contract):
    schema_version: Literal["v4.run_manifest.1"] = "v4.run_manifest.1"
    pipeline_version: Literal["v4"] = "v4"
    case_id: str = Field(pattern=_CASE_ID_PATTERN)
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    status: Literal["running", "completed", "failed"]
    input_mode: Literal["script", "goal"]
    nodes: list[ProductionNodeManifest] = Field(min_length=1)
    deliverables: list[ProductionArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_nodes(self) -> "V4RunManifest":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node IDs must be unique")
        expected_nodes = set(PRODUCTION_DAG_DEPENDENCIES)
        if set(node_ids) != expected_nodes:
            raise ValueError("run manifest must contain every frozen production DAG node exactly once")
        for node in self.nodes:
            expected_dependencies = set(PRODUCTION_DAG_DEPENDENCIES[node.node_id])
            if set(node.dependency_node_ids) != expected_dependencies:
                raise ValueError(f"node dependencies do not match frozen DAG: {node.node_id}")
        return self


class AcceptanceGateReport(V4Contract):
    schema_version: Literal["v4.acceptance_gate.1"] = "v4.acceptance_gate.1"
    gate_id: Literal["seeded_golden", "production_repository"]
    passed: bool
    ledger_object_key: str = Field(min_length=1)
    checks: list[QaCheck] = Field(min_length=1)

    @field_validator("ledger_object_key")
    @classmethod
    def validate_ledger_object_key(cls, value: str) -> str:
        return _relative_object_key(value)

    @model_validator(mode="after")
    def validate_passed(self) -> "AcceptanceGateReport":
        expected = not any(check.hard and check.status == "fail" for check in self.checks)
        if self.passed != expected:
            raise ValueError("passed must reflect all hard checks")
        return self
