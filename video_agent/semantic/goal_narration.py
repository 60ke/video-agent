from __future__ import annotations

from pathlib import Path

from video_agent.ai_runtime import AsyncModelGateway, StructuredInvocation, TraceContext
from video_agent.contracts.v4 import GoalNarrationResponse
from video_agent.io import sha256_json
from video_agent.semantic.prompts import load_goal_narration_prompt


DEFAULT_BRAND = {"name": "柯幻熊猫", "product": "AI 广告设计网站"}
DEFAULT_CAPABILITY_BOUNDARY = ["文生图设计", "图片编辑", "参考图生成", "网站落地页设计"]


async def generate_goal_narration(
    *,
    gateway: AsyncModelGateway,
    repo_root: Path,
    run_id: str,
    goal: str,
    trace_dir: Path,
    brand: dict[str, str] | None = None,
    product_capability_boundary: list[str] | None = None,
) -> tuple[GoalNarrationResponse, StructuredInvocation[GoalNarrationResponse]]:
    prompt = load_goal_narration_prompt(repo_root)
    brand_payload = brand or DEFAULT_BRAND
    boundary = product_capability_boundary or DEFAULT_CAPABILITY_BOUNDARY
    input_payload = {
        "request_id": f"goal_narration_{run_id}",
        "goal": goal.strip(),
        "brand": brand_payload,
        "product_capability_boundary": boundary,
    }
    invocation = await gateway.invoke_structured(
        capability="goal_narration",
        system_prompt=prompt.system_prompt,
        input_payload=input_payload,
        output_type=GoalNarrationResponse,
        trace_context=TraceContext(
            output_dir=trace_dir,
            prompt_version=prompt.version,
            prompt_fingerprint=prompt.fingerprint,
        ),
    )
    return invocation.value, invocation


def goal_input_fingerprint(goal: str, *, brand: dict[str, str] | None = None, boundary: list[str] | None = None) -> str:
    return sha256_json(
        {
            "goal": goal.strip(),
            "brand": brand or DEFAULT_BRAND,
            "product_capability_boundary": boundary or DEFAULT_CAPABILITY_BOUNDARY,
        }
    )
