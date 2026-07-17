from __future__ import annotations

import asyncio
import json
from pathlib import Path

from video_agent.ai_runtime import (
    AsyncModelGateway,
    CapabilityRoute,
    ModelProfile,
    ProviderProfile,
    RuntimeConfiguration,
)
from video_agent.ai_runtime.contracts import ProviderRequest, ProviderResponse
from video_agent.contracts.v4 import VideoScope
from video_agent.registries import CapabilityRegistrySnapshot
from video_agent.semantic import classify_video_scope, plan_scene_semantics


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "v4" / "stage0"
FROZEN_NARRATION = (
    "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。"
    "文化墙、门头招牌、美陈，都能一键出图。"
    "以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。"
    "细节不满意？选中它继续编辑，改完直接用。"
    "还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。"
    "设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。"
)


class QueueProvider:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.requests: list[ProviderRequest] = []

    async def complete_json(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        payload = self.payloads.pop(0)
        content = json.dumps(payload, ensure_ascii=False)
        return ProviderResponse(content=content, raw_body={"content": content}, usage={})


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _registry() -> CapabilityRegistrySnapshot:
    return CapabilityRegistrySnapshot.model_validate(_json("registry_snapshot.json"))


def _configuration() -> RuntimeConfiguration:
    provider = ProviderProfile(profile_id="test", base_url="https://example.invalid", api_key="secret")
    fast = ModelProfile(profile_id="semantic_fast", provider_profile="test", model="fast")
    quality = ModelProfile(profile_id="semantic_quality", provider_profile="test", model="quality")
    routes = {
        "scope_classifier": CapabilityRoute(capability="scope_classifier", primary="semantic_fast", max_transport_retries=0),
        "scene_semantics": CapabilityRoute(
            capability="scene_semantics",
            primary="semantic_fast",
            repair="semantic_fast",
            rebuild="semantic_quality",
            max_transport_retries=0,
        ),
        "field_repair": CapabilityRoute(capability="field_repair", primary="semantic_fast", max_transport_retries=0),
    }
    return RuntimeConfiguration(
        providers={"test": provider},
        models={"semantic_fast": fast, "semantic_quality": quality},
        routes=routes,
    )


def _scope() -> VideoScope:
    return VideoScope.model_validate(_json("video_scope.payload.json"))


def test_scope_stage_builds_validated_envelope_and_trace(tmp_path: Path) -> None:
    provider = QueueProvider([_json("video_scope.payload.json")])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})
    envelope, invocation = asyncio.run(
        classify_video_scope(
            gateway=gateway,
            repo_root=REPO_ROOT,
            run_id="run_1",
            frozen_narration=FROZEN_NARRATION,
            registry=_registry(),
            trace_dir=tmp_path / "01_scope_classifier",
        )
    )
    assert envelope.schema_version == "v4.video_scope.1"
    assert envelope.payload.categories[0].is_primary is True
    assert invocation.replayed is False
    assert "frozen_narration" in envelope.input_fingerprints
    assert provider.requests[0].input_payload.keys() == {"request_id", "frozen_narration", "enabled_categories"}


def test_scene_stage_accepts_golden_plan(tmp_path: Path) -> None:
    provider = QueueProvider([_json("scene_semantic_plan.payload.json")])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})
    envelope, _ = asyncio.run(
        plan_scene_semantics(
            gateway=gateway,
            repo_root=REPO_ROOT,
            run_id="run_1",
            frozen_narration=FROZEN_NARRATION,
            video_scope=_scope(),
            registry=_registry(),
            trace_dir=tmp_path / "02_scene_semantics",
        )
    )
    assert envelope.schema_version == "v4.scene_semantics.1"
    assert len(envelope.payload.scenes) == 10
    request = provider.requests[0].input_payload
    assert "assets" not in request
    assert "registry_snapshot" in request


def test_scene_stage_repairs_one_registry_field(tmp_path: Path) -> None:
    invalid = _json("scene_semantic_plan.payload.json")
    invalid["scenes"][0]["slots"][0]["asset_role"] = "site_hmoe"
    patch = {"op": "replace", "path": "/scenes/0/slots/0/asset_role", "value": "site_home"}
    provider = QueueProvider([invalid, patch])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})
    trace_dir = tmp_path / "02_scene_semantics"
    envelope, _ = asyncio.run(
        plan_scene_semantics(
            gateway=gateway,
            repo_root=REPO_ROOT,
            run_id="run_1",
            frozen_narration=FROZEN_NARRATION,
            video_scope=_scope(),
            registry=_registry(),
            trace_dir=trace_dir,
        )
    )
    assert envelope.payload.scenes[0].slots[0].asset_role == "site_home"
    manifest = json.loads((trace_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["repair_count"] == 1
    assert manifest["rebuild_count"] == 0


def test_scene_stage_rebuilds_nonlocal_contract_failure(tmp_path: Path) -> None:
    invalid = _json("scene_semantic_plan.payload.json")
    invalid["scenes"][0]["text"] = invalid["scenes"][0]["text"].replace("柯幻熊猫", "其他网站")
    provider = QueueProvider([invalid, _json("scene_semantic_plan.payload.json")])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})
    trace_dir = tmp_path / "02_scene_semantics"
    envelope, invocation = asyncio.run(
        plan_scene_semantics(
            gateway=gateway,
            repo_root=REPO_ROOT,
            run_id="run_1",
            frozen_narration=FROZEN_NARRATION,
            video_scope=_scope(),
            registry=_registry(),
            trace_dir=trace_dir,
        )
    )
    assert len(envelope.payload.scenes) == 10
    assert invocation.model_profile == "semantic_quality"
    manifest = json.loads((trace_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["rebuild_count"] == 1
