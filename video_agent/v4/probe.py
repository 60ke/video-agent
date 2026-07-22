"""Stepwise V4 probe helpers: checkpoint map + human-readable run summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# User-facing checkpoints for --until / stepwise tuning.
PROBE_CHECKPOINTS: tuple[dict[str, Any], ...] = (
    {
        "id": "scene",
        "label": "语义前端完成（口播+Scope+Scene）",
        "ai": ["Scope Classifier", "Scene Semantics"],
        "program": ["冻结文案", "TTS/SpeechTimingLock", "Scene 校验与确定性 repair"],
        "watch": [
            "frozen_narration.json",
            "video_scope.json",
            "scene_semantic_plan.json",
            "agents/01_scope_classifier/response.validated.json",
            "agents/02_scene_semantics/response.validated.json",
            "speech_timing_lock.json",
        ],
    },
    {
        "id": "assets",
        "label": "素材选配完成（Stage4）",
        "ai": [],
        "program": ["结构化查询", "加权选择", "派生补缺"],
        "watch": [
            "resolved_asset_plan.json",
            "selection_decisions.json",
            "derivation_requests.json",
            "material_gaps.json",
            "asset_repository.snapshot.json",
        ],
    },
    {
        "id": "anchor",
        "label": "词级锚点完成",
        "ai": [],
        "program": ["PhraseAnchor 编译"],
        "watch": ["anchored_timing_plan.json"],
    },
    {
        "id": "motion_audio",
        "label": "动效/音效分配完成（Stage5）",
        "ai": [],
        "program": ["Effect/SFX 加权分配"],
        "watch": ["motion_audio_plan.json"],
    },
    {
        "id": "compile",
        "label": "时间线编译完成（不渲染成片）",
        "ai": [],
        "program": ["视觉轨/字幕/SFX 编译", "Claim 证据告警"],
        "watch": [
            "compiled_video_timeline.json",
            "stage6_validation.json",
            "render/remotion.timeline.json",
        ],
    },
    {
        "id": "render",
        "label": "成片渲染完成",
        "ai": [],
        "program": ["Remotion + FFmpeg", "封面", "QA"],
        "watch": ["final/video.mp4", "final/cover.png", "run_manifest.json"],
    },
)

CHECKPOINT_IDS = tuple(item["id"] for item in PROBE_CHECKPOINTS)


def probe_map() -> dict[str, Any]:
    return {
        "ok": True,
        "checkpoints": list(PROBE_CHECKPOINTS),
        "legacy_stage_cli": [
            "python main.py v4-stage1 --case <case> [--resume <run>]",
            "python main.py v4-stage4 --case <case> --resume <run>",
            "python main.py v4-stage6 --case <case> --resume <run> --phase anchor",
            "python main.py v4-stage5 --case <case> --resume <run>",
            "python main.py v4-stage6 --case <case> --resume <run> --phase compile-render [--render]",
        ],
        "probe_cli": [
            "python main.py v4-probe map",
            "python main.py v4-probe show --case <case> [--run <run_id>]",
            "python main.py v4-probe run --script <txt> --case-id <id> --until scene|assets|anchor|motion_audio|compile|render",
        ],
    }


def _load_payload(path: Path) -> Any | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "payload" in data and isinstance(data["payload"], (dict, list)):
        # Common ArtifactEnvelope wrappers.
        if path.name in {
            "scene_semantic_plan.json",
            "video_scope.json",
            "resolved_asset_plan.json",
            "frozen_narration.json",
            "asset_repository.snapshot.json",
        }:
            return data["payload"]
    return data


def _resolve_run_dir(case_dir: Path, run_id: str | None) -> Path:
    if run_id:
        run_dir = case_dir / "runs" / run_id
        if not run_dir.is_dir():
            raise FileNotFoundError(f"run not found: {run_dir}")
        return run_dir
    latest = case_dir / "latest_run.json"
    if latest.is_file():
        rid = json.loads(latest.read_text(encoding="utf-8")).get("run_id")
        if rid:
            return _resolve_run_dir(case_dir, str(rid))
    runs = case_dir / "runs"
    if not runs.is_dir():
        raise FileNotFoundError(f"no runs under {case_dir}")
    candidates = sorted((p for p in runs.iterdir() if p.is_dir()), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"no runs under {case_dir}")
    return candidates[0]


def summarize_run(case_dir: Path, run_id: str | None = None) -> dict[str, Any]:
    run_dir = _resolve_run_dir(case_dir, run_id)
    present = {
        rel: (run_dir / rel).is_file()
        for item in PROBE_CHECKPOINTS
        for rel in item["watch"]
    }
    reached = []
    for item in PROBE_CHECKPOINTS:
        if all((run_dir / rel).is_file() for rel in item["watch"] if not rel.startswith("agents/")):
            # agents optional for "reached"; require primary plan files
            primary = [rel for rel in item["watch"] if "/" not in rel or rel.startswith("final/")]
            if primary and all((run_dir / rel).is_file() for rel in primary):
                reached.append(item["id"])

    scope = _load_payload(run_dir / "video_scope.json")
    scene = _load_payload(run_dir / "scene_semantic_plan.json")
    resolved = _load_payload(run_dir / "resolved_asset_plan.json")
    timeline = _load_payload(run_dir / "compiled_video_timeline.json")
    snap = _load_payload(run_dir / "asset_repository.snapshot.json")
    validation = _load_payload(run_dir / "stage6_validation.json")

    assets_by_ref: dict[str, Any] = {}
    if isinstance(snap, dict):
        for asset in snap.get("assets") or []:
            ref = asset.get("asset_ref")
            if ref:
                assets_by_ref[ref] = asset

    slot_assets: dict[tuple[str, str], str] = {}
    if isinstance(resolved, dict):
        for rs in resolved.get("scenes") or []:
            for slot in rs.get("slots") or []:
                ref = slot.get("asset_ref")
                if ref:
                    slot_assets[(rs.get("scene_id"), slot.get("slot_id"))] = ref

    scenes_out: list[dict[str, Any]] = []
    if isinstance(scene, dict):
        for sc in scene.get("scenes") or []:
            sid = sc.get("scene_id")
            slots = []
            for slot in sc.get("slots") or []:
                ref = slot_assets.get((sid, slot.get("slot_id")))
                object_key = None
                if ref and ref in assets_by_ref:
                    object_key = assets_by_ref[ref].get("object_key")
                # timeline render_assets fallback
                slots.append(
                    {
                        "slot_id": slot.get("slot_id"),
                        "asset_role": slot.get("asset_role"),
                        "category_id": slot.get("category_id"),
                        "anchor_phrase": slot.get("anchor_phrase"),
                        "source_kind": (slot.get("source") or {}).get("kind"),
                        "asset_ref": ref,
                        "object_key": object_key,
                    }
                )
            scenes_out.append(
                {
                    "scene_id": sid,
                    "text": (sc.get("text") or "").strip(),
                    "visual_structure": sc.get("visual_structure"),
                    "no_asset": sc.get("no_asset"),
                    "slots": slots,
                    "claims": [
                        {
                            "claim_id": c.get("claim_id"),
                            "phrase": c.get("phrase"),
                            "supporting_slots": c.get("supporting_slots"),
                        }
                        for c in (sc.get("claims") or [])
                    ],
                }
            )

    # fill object_key from timeline render_assets if missing
    if isinstance(timeline, dict):
        render = {a.get("asset_ref"): a for a in timeline.get("render_assets") or []}
        for sc in scenes_out:
            for slot in sc["slots"]:
                ref = slot.get("asset_ref")
                if ref and not slot.get("object_key") and ref in render:
                    slot["object_key"] = render[ref].get("object_key")

    subs: list[dict[str, Any]] = []
    if isinstance(timeline, dict):
        fps = float(timeline.get("fps") or 30)
        for cue in timeline.get("subtitle_track") or []:
            subs.append(
                {
                    "scene_id": cue.get("scene_id"),
                    "text": cue.get("text"),
                    "start_s": round(cue.get("start_frame", 0) / fps, 3),
                    "end_s": round(cue.get("end_frame", 0) / fps, 3),
                }
            )

    warnings = []
    if isinstance(validation, dict):
        warnings = list(validation.get("warnings") or [])

    return {
        "ok": True,
        "case": case_dir.as_posix(),
        "run_id": run_dir.name,
        "run_dir": run_dir.as_posix(),
        "artifacts_present": present,
        "checkpoints_reached": reached,
        "scope": scope,
        "scenes": scenes_out,
        "subtitles": subs,
        "stage6_warnings": warnings,
        "final_video": (
            (run_dir / "final" / "video.mp4").as_posix()
            if (run_dir / "final" / "video.mp4").is_file()
            else None
        ),
    }


def format_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"run: {summary.get('run_id')}")
    lines.append(f"dir: {summary.get('run_dir')}")
    lines.append(f"checkpoints: {', '.join(summary.get('checkpoints_reached') or []) or '(none)'}")
    scope = summary.get("scope") or {}
    if scope:
        cats = scope.get("categories") or []
        cat_txt = ", ".join(
            f"{c.get('category_id')}{'*' if c.get('is_primary') else ''}" for c in cats
        )
        lines.append(f"scope: {scope.get('scope_mode')} | {cat_txt}")
    lines.append("")
    for sc in summary.get("scenes") or []:
        flag = " [no_asset]" if sc.get("no_asset") else ""
        lines.append(f"## {sc.get('scene_id')} {sc.get('visual_structure')}{flag}")
        lines.append(f"  text: {sc.get('text')}")
        if not sc.get("slots"):
            lines.append("  slots: (none)")
        for slot in sc.get("slots") or []:
            lines.append(
                "  slot {sid}: role={role} cat={cat} phrase={phrase} -> {ref} {path}".format(
                    sid=slot.get("slot_id"),
                    role=slot.get("asset_role"),
                    cat=slot.get("category_id"),
                    phrase=slot.get("anchor_phrase"),
                    ref=slot.get("asset_ref") or "(unresolved)",
                    path=slot.get("object_key") or "",
                )
            )
        for claim in sc.get("claims") or []:
            lines.append(
                f"  claim {claim.get('claim_id')}: {claim.get('phrase')} supports={claim.get('supporting_slots')}"
            )
        lines.append("")
    if summary.get("subtitles"):
        lines.append("## subtitles")
        for cue in summary["subtitles"]:
            lines.append(
                f"  [{cue['start_s']:.2f}-{cue['end_s']:.2f}] {cue.get('scene_id')} {cue.get('text')}"
            )
        lines.append("")
    warnings = summary.get("stage6_warnings") or []
    if warnings:
        lines.append("## stage6 warnings")
        for warning in warnings:
            lines.append(f"  {warning}")
    if summary.get("final_video"):
        lines.append(f"final_video: {summary['final_video']}")
    return "\n".join(lines).rstrip() + "\n"
