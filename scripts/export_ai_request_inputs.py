from __future__ import annotations

"""Export reproducible, API-key-free AI request inputs from an existing run.

The pipeline historically persisted model responses, not every request payload.
This utility reconstructs the initial text-planner calls from run artifacts and
exports planned GPT Image requests with their original source-image order.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from video_agent.ai.action_scene_planner import _asset_payload, _timing_payload
from video_agent.ai.asset_index import AIAssetIndex, translate_relationships_for_ai
from video_agent.ai.asset_selector import compact_asset_table
from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.assets.materializer import _prompt, _provider_signature, _resolve_source, _target_size
from video_agent.contracts import AssetCatalog, CaseConfig, DeriveKind, Narration, TimingLock
from video_agent.io import load_json, load_model, write_json_atomic


def _eligible_assets(catalog: AssetCatalog) -> list[Any]:
    return [
        asset
        for asset in catalog.assets
        if asset.production_eligible
        and asset.quality.status != "rejected"
        and asset.role != "outro"
        and asset.media_type != "audio"
    ]


def _provider_request(
    *,
    client: OpenAICompatibleTextClient,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    thinking: bool,
    schema_name: str,
    request_status: str,
    notes: list[str],
) -> dict[str, Any]:
    endpoint = f"{client.base_url}/chat/completions" if client.base_url.endswith("/v1") else f"{client.base_url}/v1/chat/completions"
    return {
        "schema_version": 1,
        "kind": "openai_compatible_text_json",
        "request_status": request_status,
        "schema_name": schema_name,
        "endpoint": endpoint,
        "model": model,
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"} if not thinking else {"type": "enabled"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "notes": notes,
    }


def _case_dir_for_run(run_dir: Path) -> Path:
    if run_dir.parent.name != "runs":
        raise ValueError(f"run directory must be cases/<case>/runs/<run>: {run_dir}")
    return run_dir.parent.parent


def _prompt_match(manifest: dict[str, Any], prompt_path: Path, prompt_sha256: str) -> str:
    expected = [item for item in manifest.get("prompts", []) if isinstance(item, dict) and item.get("path") == prompt_path.as_posix()]
    if not expected:
        return "The run manifest did not record this prompt path; this export uses the current checked-out template."
    if any(item.get("sha256") == prompt_sha256 for item in expected):
        return "The current prompt template SHA256 matches the prompt recorded in this run."
    return "WARNING: current prompt template differs from the SHA256 recorded in this run; this is a best-effort reconstruction."


def _write_text_requests(repo_root: Path, case_dir: Path, run_dir: Path, output_dir: Path) -> list[dict[str, str]]:
    manifest = load_json(run_dir / "run_manifest.json")
    case = load_model(case_dir / "case.json", CaseConfig)
    narration = load_model(run_dir / "narration.json", Narration)
    timing = load_model(run_dir / "timing_lock.json", TimingLock)
    catalog = load_model(run_dir / "asset_catalog.source.json", AssetCatalog)
    selection = load_json(run_dir / "asset_selection.json") if (run_dir / "asset_selection.json").is_file() else {}
    relationships_path = repo_root / "assets" / "relationships.json"
    relationships = load_json(relationships_path).get("relationships", []) if relationships_path.is_file() else []
    client = OpenAICompatibleTextClient(repo_root)
    traces: list[dict[str, str]] = []

    eligible = _eligible_assets(catalog)
    asset_index = AIAssetIndex.build(eligible)
    selected_ids = {asset.asset_id for asset in eligible if asset.asset_id in set(selection.get("candidate_asset_ids", []))}
    candidates = [asset for asset in eligible if asset.asset_id in selected_ids]
    if not candidates:
        candidates = eligible

    selector_prompt = load_prompt(repo_root / "video_agent" / "prompts" / "asset_coarse_selector.md")
    required_refs = sorted(
        {
            ref
            for asset_id in case.selected_asset_ids
            for ref in asset_index.refs_for_asset_id(asset_id)
        }
    )
    selector_user = json.dumps(
        {
            "case": {"case_id": case.case_id, "goal": case.goal, "feature_path": case.feature_path},
            "narration": narration.model_dump(mode="json"),
            "assets": compact_asset_table(eligible, asset_index),
            "required_asset_refs": required_refs,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    selector_request = _provider_request(
        client=client,
        system=selector_prompt.text,
        user=selector_user,
        model=client.coarse_model,
        max_tokens=4096,
        thinking=False,
        schema_name="asset_coarse_selector",
        request_status="reconstructed_initial_request",
        notes=[_prompt_match(manifest, selector_prompt.path, selector_prompt.sha256), "No API key is included."],
    )
    write_json_atomic(output_dir / "01_asset_coarse_selector.initial.request.json", selector_request)
    traces.append({"name": "asset_coarse_selector", "path": "01_asset_coarse_selector.initial.request.json"})

    planner_prompt = load_prompt(repo_root / "video_agent" / "prompts" / "action_scene_planner.md")
    selected_relationships = selection.get("relationships") if isinstance(selection.get("relationships"), list) else []
    payload = {
        "case": {"case_id": case.case_id, "goal": case.goal, "feature_path": case.feature_path},
        "narration": narration.model_dump(mode="json"),
        "timing": _timing_payload(timing),
        "assets": _asset_payload(
            AssetCatalog(
                catalog_id=f"candidates_{catalog.catalog_id}",
                generated_at=catalog.generated_at,
                source_root=catalog.source_root,
                assets=candidates,
                source_catalog_sha256=catalog.source_catalog_sha256,
                warnings=list(catalog.warnings),
            ),
            asset_index,
        ),
        "asset_selection_mode": selection.get("mode"),
        "asset_selection_fallback": (
            {"reason": "flash_contract_failed", "fallback": "full_catalog_to_pro"}
            if selection.get("flash_failure")
            else None
        ),
        "candidate_groups": selection.get("flash_result"),
        "relationships": {"relationships": translate_relationships_for_ai(selected_relationships, asset_index)},
    }
    planner_request = _provider_request(
        client=client,
        system=planner_prompt.text,
        user=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        model=client.model,
        max_tokens=4096,
        thinking=False,
        schema_name="action_scene",
        request_status="reconstructed_initial_request",
        notes=[_prompt_match(manifest, planner_prompt.path, planner_prompt.sha256), "No API key is included."],
    )
    write_json_atomic(output_dir / "02_action_scene.initial.request.json", planner_request)
    traces.append({"name": "action_scene", "path": "02_action_scene.initial.request.json"})

    cover_prompt = load_prompt(repo_root / "video_agent" / "prompts" / "cover_title_planner.md")
    cover_user = json.dumps(
        {
            "goal": case.goal,
            "feature_path": case.feature_path,
            "full_narration": [
                {"beat_id": beat.beat_id, "spoken_text": beat.spoken_text} for beat in narration.beats
            ],
        },
        ensure_ascii=False,
    )
    cover_request = _provider_request(
        client=client,
        system=cover_prompt.text,
        user=cover_user,
        model=client.model,
        max_tokens=256,
        thinking=False,
        schema_name="cover_title",
        request_status="would_run_after_successful_render",
        notes=["This failed run did not reach cover generation; this is the exact request it would send after render.", "No API key is included."],
    )
    write_json_atomic(output_dir / "03_cover_title.would_run.request.json", cover_request)
    traces.append({"name": "cover_title", "path": "03_cover_title.would_run.request.json"})
    return traces


def _write_image_requests(repo_root: Path, run_dir: Path, output_dir: Path) -> list[dict[str, str]]:
    plan_path = run_dir / "asset_preparation_plan.json"
    catalog_path = run_dir / "asset_catalog.source.json"
    if not plan_path.is_file() or not catalog_path.is_file():
        return []
    plan = load_json(plan_path)
    catalog = load_model(catalog_path, AssetCatalog)
    by_id = {asset.asset_id: asset for asset in catalog.assets}
    signature = _provider_signature(repo_root)
    traces: list[dict[str, str]] = []
    for index, request in enumerate(plan.get("requests", []), start=1):
        if not isinstance(request, dict):
            continue
        source = by_id.get(str(request.get("source_asset_id")))
        if source is None:
            continue
        related = [by_id.get(str(asset_id)) for asset_id in request.get("related_asset_ids", [])]
        if any(asset is None for asset in related):
            continue
        kind = DeriveKind(str(request["derive_kind"]))
        prompt, prompt_sha256 = _prompt(repo_root, kind, str(request.get("instruction") or ""))
        target_size = _target_size(request.get("target_orientation"), signature)
        if request.get("target_orientation"):
            prompt += f"\nRequired output orientation: {request['target_orientation']}. Required output size: {target_size}."
        sources = [source, *[asset for asset in related if asset is not None]]
        record = {
            "schema_version": 1,
            "kind": "openai_compatible_image_edit",
            "request_status": "planned_or_cached_request",
            "endpoint": signature.get("base_url", "").rstrip("/") + "/v1/images/edits",
            "model": signature.get("model"),
            "form_fields": {"model": signature.get("model"), "prompt": prompt, "size": target_size, "quality": "configured_provider_quality"},
            "derive_request": request,
            "input_images_in_exact_panel_order": [
                {"asset_id": asset.asset_id, "path": _resolve_source(repo_root, asset).as_posix()} for asset in sources
            ],
            "image_panel_instruction": "When there is more than one input image, the runtime creates one horizontal composite with panels A, B, C in the listed order and sends that composite as the single image multipart field.",
            "prompt_template_sha256": prompt_sha256,
            "notes": ["No API key is included.", "The pipeline may reuse a cached derivative instead of sending this request."],
        }
        name = f"10_gpt_image_{index:02d}_{kind.value}.request.json"
        write_json_atomic(output_dir / name, record)
        traces.append({"name": f"gpt_image:{kind.value}", "path": name})
    return traces


def export_run(repo_root: Path, run_dir: Path, output_root: Path) -> Path:
    run_dir = run_dir.resolve()
    case_dir = _case_dir_for_run(run_dir)
    target = output_root / case_dir.name / run_dir.name
    target.mkdir(parents=True, exist_ok=True)
    text_requests = _write_text_requests(repo_root, case_dir, run_dir, target)
    image_requests = _write_image_requests(repo_root, run_dir, target)
    write_json_atomic(
        target / "manifest.json",
        {
            "schema_version": 1,
            "case_dir": case_dir.as_posix(),
            "run_dir": run_dir.as_posix(),
            "requests": [*text_requests, *image_requests],
            "limitations": [
                "Historical correction-round requests are not recoverable because the old runtime persisted only final model responses.",
                "All exports omit API keys and binary/base64 image payloads.",
            ],
        },
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Export raw AI planner inputs from existing video-agent runs.")
    parser.add_argument("--run", action="append", required=True, help="Run directory; repeat for multiple runs.")
    parser.add_argument("--output", required=True, help="Directory for exported request JSON files.")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_root = Path(args.output).resolve()
    for raw_run in args.run:
        target = export_run(repo_root, Path(raw_run), output_root)
        print(target.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
