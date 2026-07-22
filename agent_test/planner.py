from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

SCENE_KINDS = {
    "website_operation",
    "result_detail",
    "result_gallery",
    "before_after",
    "title_card",
}

_WEBSITE_WORDS = ("上传", "选择", "输入", "点击", "打开", "网站", "页面", "生成按钮", "操作")
_RESULT_WORDS = ("结果", "效果图", "案例", "出图", "生成了", "看右边", "展示")
_GALLERY_WORDS = ("多个", "一组", "各种", "海报", "文化墙", "门头", "美陈", "案例")
_COMPARE_WORDS = ("之前", "之后", "前后", "原图", "改完", "参考图")


@dataclass(frozen=True)
class PlannerConfig:
    api_base: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = 90.0

    @classmethod
    def from_env(cls) -> "PlannerConfig":
        return cls(
            api_base=(os.getenv("AGENT_TEST_API_BASE") or "").strip() or None,
            api_key=(os.getenv("AGENT_TEST_API_KEY") or "").strip() or None,
            model=(os.getenv("AGENT_TEST_MODEL") or "").strip() or None,
        )


class ScenePlanner:
    """Small planning agent with a deterministic fallback.

    An OpenAI-compatible chat endpoint may be configured through environment
    variables. Without it, the same pipeline remains runnable with transparent
    keyword rules, which is useful for validating CDP capture and Remotion first.
    """

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self.config = config or PlannerConfig.from_env()

    def plan(
        self,
        cues: list[dict[str, Any]],
        *,
        recipes: dict[str, Any],
        result_assets: list[str],
    ) -> list[dict[str, Any]]:
        if self.config.api_base and self.config.api_key and self.config.model:
            try:
                return self._plan_with_llm(cues, recipes=recipes, result_assets=result_assets)
            except Exception as exc:
                print(f"[agent-test] planner API failed, using deterministic fallback: {exc}")
        return self._plan_deterministically(cues, recipes=recipes, result_assets=result_assets)

    def _plan_with_llm(
        self,
        cues: list[dict[str, Any]],
        *,
        recipes: dict[str, Any],
        result_assets: list[str],
    ) -> list[dict[str, Any]]:
        endpoint = self.config.api_base.rstrip("/") + "/chat/completions"
        compact_cues = [
            {
                "cue_id": cue["cue_id"],
                "text": cue["text"],
                "start_ms": cue["start_ms"],
                "end_ms": cue["end_ms"],
            }
            for cue in cues
        ]
        prompt = {
            "task": "Classify each spoken cue into a visual scene for a short product-demo video.",
            "rules": [
                "Return one scene for every cue, preserving cue order and timing exactly.",
                "Use website_operation for real website steps such as open/upload/select/fill/click/generate.",
                "website_operation must reference an existing recipe_id; never invent one.",
                "Use result_detail/result_gallery for generated images and result showcases.",
                "Use before_after only when the spoken text explicitly describes a comparison.",
                "Use title_card when no truthful visual evidence is available.",
                "Do not change narration text or timestamps.",
            ],
            "scene_kinds": sorted(SCENE_KINDS),
            "recipes": list(recipes.keys()),
            "result_assets": result_assets,
            "cues": compact_cues,
            "output_schema": {
                "scenes": [
                    {
                        "cue_id": "cue_001",
                        "kind": "website_operation",
                        "recipe_id": "optional-existing-id",
                        "asset_paths": ["optional/result.png"],
                        "motion": "optional-short-motion-name",
                    }
                ]
            },
        }
        payload = {
            "model": self.config.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a precise video scene planning agent. Output JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_json_fence(content))
        proposals = parsed.get("scenes")
        if not isinstance(proposals, list):
            raise ValueError("planner response has no scenes list")
        proposal_by_cue = {str(item.get("cue_id")): item for item in proposals if isinstance(item, dict)}
        scenes: list[dict[str, Any]] = []
        for cue in cues:
            proposal = proposal_by_cue.get(cue["cue_id"], {})
            scenes.append(self._normalize_scene(cue, proposal, recipes=recipes, result_assets=result_assets))
        return scenes

    def _plan_deterministically(
        self,
        cues: list[dict[str, Any]],
        *,
        recipes: dict[str, Any],
        result_assets: list[str],
    ) -> list[dict[str, Any]]:
        recipe_ids = list(recipes.keys())
        scenes: list[dict[str, Any]] = []
        result_index = 0
        for cue in cues:
            text = cue["text"]
            proposal: dict[str, Any] = {}
            if any(word in text for word in _WEBSITE_WORDS) and recipe_ids:
                proposal = {"kind": "website_operation", "recipe_id": recipe_ids[0], "motion": "screen_push"}
            elif any(word in text for word in _COMPARE_WORDS) and len(result_assets) >= 2:
                proposal = {"kind": "before_after", "asset_paths": result_assets[:2], "motion": "wipe_compare"}
            elif any(word in text for word in _RESULT_WORDS) and result_assets:
                kind = "result_gallery" if any(word in text for word in _GALLERY_WORDS) and len(result_assets) > 1 else "result_detail"
                count = min(4, len(result_assets)) if kind == "result_gallery" else 1
                selected = [result_assets[(result_index + offset) % len(result_assets)] for offset in range(count)]
                result_index += count
                proposal = {"kind": kind, "asset_paths": selected, "motion": "slide_gallery" if count > 1 else "slow_zoom"}
            else:
                proposal = {"kind": "title_card", "motion": "text_pop"}
            scenes.append(self._normalize_scene(cue, proposal, recipes=recipes, result_assets=result_assets))
        return scenes

    @staticmethod
    def _normalize_scene(
        cue: dict[str, Any],
        proposal: dict[str, Any],
        *,
        recipes: dict[str, Any],
        result_assets: list[str],
    ) -> dict[str, Any]:
        kind = str(proposal.get("kind") or "title_card")
        if kind not in SCENE_KINDS:
            kind = "title_card"
        recipe_id = str(proposal.get("recipe_id") or "") or None
        if kind == "website_operation" and recipe_id not in recipes:
            kind = "result_detail" if result_assets else "title_card"
            recipe_id = None
        assets = [str(path) for path in proposal.get("asset_paths") or [] if str(path) in result_assets]
        if kind in {"result_detail", "result_gallery", "before_after"} and not assets:
            assets = result_assets[: 2 if kind == "before_after" else 4 if kind == "result_gallery" else 1]
        if kind in {"result_detail", "result_gallery", "before_after"} and not assets:
            kind = "title_card"
        return {
            "scene_id": f"scene_{cue['cue_id'].split('_')[-1]}",
            "cue_id": cue["cue_id"],
            "text": cue["text"],
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "start_frame": cue["start_frame"],
            "end_frame": cue["end_frame"],
            "kind": kind,
            "recipe_id": recipe_id,
            "asset_paths": assets,
            "motion": str(proposal.get("motion") or "fade"),
        }


def _strip_json_fence(value: str) -> str:
    value = value.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, re.DOTALL)
    return match.group(1) if match else value
