from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_agent.ai_runtime.routing import load_runtime_configuration
from video_agent.contracts.v4 import (
    PRODUCTION_DAG_DEPENDENCIES,
    AcceptanceGateReport,
    BgmDuckingConfig,
    BgmPlan,
    CoverBrief,
    GoalNarrationResponse,
    ProductionArtifact,
    ProductionBgmConfig,
    ProductionNodeManifest,
    QaCheck,
    StructuredQaReport,
    V4ProductionCase,
    V4RunManifest,
)
from video_agent.semantic.prompts import load_goal_narration_prompt


REPO_ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64


def test_production_case_freezes_real_voice_and_disabled_bgm() -> None:
    case = V4ProductionCase(
        case_id="video_20260720_ab12",
        input_mode="script",
        script_object_key="input/source_script.txt",
        random_seed="seed-1",
    )
    assert case.voice_profile_id == "minimax_adman_clear_01"
    assert case.bgm == ProductionBgmConfig(enabled=False, profile_id=None)
    assert case.cover.enabled is True
    assert case.outro.enabled is True


def test_production_case_rejects_ambiguous_or_host_input() -> None:
    with pytest.raises(ValidationError, match="script mode cannot set goal"):
        V4ProductionCase(
            case_id="video_20260720_ab12",
            input_mode="script",
            goal="duplicate source",
            script_object_key="input/source_script.txt",
            random_seed="seed-1",
        )
    with pytest.raises(ValidationError, match="relative POSIX"):
        V4ProductionCase(
            case_id="video_20260720_ab12",
            input_mode="script",
            script_object_key=r"C:\copy\script.txt",
            random_seed="seed-1",
        )
    with pytest.raises(ValidationError, match="enabled BGM requires profile_id"):
        ProductionBgmConfig(enabled=True)


def test_goal_narration_contract_and_prompt_are_frozen() -> None:
    response = GoalNarrationResponse(
        schema_version="v4.goal_narration.1",
        spoken_text="打开柯幻熊猫，一套流程完成广告设计。",
        language="zh-CN",
    )
    assert response.language == "zh-CN"
    with pytest.raises(ValidationError):
        GoalNarrationResponse.model_validate({**response.model_dump(), "shots": []})
    with pytest.raises(ValidationError, match="Markdown"):
        GoalNarrationResponse(
            schema_version="v4.goal_narration.1",
            spoken_text="```json\n{}\n```",
            language="zh-CN",
        )

    prompt = load_goal_narration_prompt(REPO_ROOT)
    assert prompt.capability == "goal_narration"
    assert prompt.version == "goal_narration.v1"
    assert prompt.input_schema["additionalProperties"] is False
    assert prompt.output_schema["required"] == ["schema_version", "spoken_text", "language"]
    assert set(prompt.component_fingerprints) == {"system", "examples"}
    for heading in ("# Role", "# Goal", "# Inputs", "# Allowed Decisions", "# Forbidden Decisions", "# Output Contract"):
        assert heading in prompt.system_prompt


def test_goal_narration_route_is_independent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VIDEO_AGENT_AI_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("VIDEO_AGENT_AI_API_KEY", "not-a-real-secret")
    configuration = load_runtime_configuration(tmp_path)
    route = configuration.routes["goal_narration"]
    assert route.capability == "goal_narration"
    assert route.primary == "semantic_fast"
    assert route.rebuild == "semantic_quality"


def test_bgm_plan_uses_frozen_relative_audio_asset() -> None:
    plan = BgmPlan(
        profile_id="douyin_clean_01",
        profile_content_sha256=SHA,
        object_key="assets/audio/bgm/clean.wav",
        media_content_sha256=SHA,
        gain_db=-22.0,
        loop=True,
        duck_under_voice=True,
        ducking=BgmDuckingConfig(threshold=0.025, ratio=8.0, attack_ms=12, release_ms=260),
    )
    assert plan.object_key == "assets/audio/bgm/clean.wav"
    with pytest.raises(ValidationError, match="relative POSIX"):
        BgmPlan.model_validate({**plan.model_dump(), "object_key": r"C:\audio\clean.wav"})


def test_cover_brief_requires_full_narration_and_official_logo() -> None:
    brief = CoverBrief(
        narration_sha256=SHA,
        video_scope_sha256=SHA,
        full_narration_text="完整文案，不是首句。",
        title="广告设计一站完成",
        representative_asset_refs=["asset://A0001"],
    )
    assert brief.brand_logo_object_key.endswith("柯幻熊猫_LOGO.png")
    with pytest.raises(ValidationError):
        CoverBrief.model_validate({**brief.model_dump(), "brand_logo_object_key": "assets/brand/other.png"})


def test_qa_reports_are_self_consistent() -> None:
    passed = QaCheck(check_id="anchor_alignment", status="pass", message="aligned")
    report = StructuredQaReport(timeline_sha256=SHA, passed=True, checks=[passed])
    assert report.passed is True
    with pytest.raises(ValidationError, match="passed must reflect"):
        StructuredQaReport(
            timeline_sha256=SHA,
            passed=True,
            checks=[QaCheck(check_id="anchor_alignment", status="fail", message="off by two frames")],
        )


def test_run_manifest_and_acceptance_gates_use_relative_artifacts() -> None:
    nodes = [
        ProductionNodeManifest(
            node_id=node_id,
            status="completed",
            dependency_node_ids=list(dependencies),
            outputs=(
                [ProductionArtifact(object_key="final/video.mp4", content_sha256=SHA)]
                if node_id == "finalize"
                else []
            ),
        )
        for node_id, dependencies in PRODUCTION_DAG_DEPENDENCIES.items()
    ]
    manifest = V4RunManifest(
        case_id="video_20260720_ab12",
        run_id="20260720_120000_ab12",
        status="completed",
        input_mode="script",
        nodes=nodes,
        deliverables=nodes[-1].outputs,
    )
    assert manifest.pipeline_version == "v4"
    gate = AcceptanceGateReport(
        gate_id="seeded_golden",
        passed=True,
        ledger_object_key="tests/fixtures/v4/stage6/pass_b_ledger.json",
        checks=[QaCheck(check_id="golden_render", status="pass", message="passed")],
    )
    assert gate.gate_id == "seeded_golden"

    rendered_schema = json.dumps(GoalNarrationResponse.model_json_schema(), ensure_ascii=False)
    assert "spoken_text" in rendered_schema
