"""V4 Production DAG orchestrator (Stage7 Units 3–4 core)."""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import (
    CoverBrief,
    DeliveryQaReport,
    FrozenNarration,
    ProductionArtifact,
    ProductionNodeManifest,
    QaCheck,
    StructuredQaReport,
    V4RunManifest,
    VideoScope,
)
from video_agent.contracts.v4.production import PRODUCTION_DAG_DEPENDENCIES, ProductionNodeId, _OFFICIAL_BRAND_LOGO
from video_agent.io import load_json, load_model, sha256_file, sha256_json, utc_now, write_json_atomic
from video_agent.progress import get_logger
from video_agent.runtime import RunContext
from video_agent.v4.orchestrator import V4Orchestrator


logger = get_logger()

NODE_ORDER: list[ProductionNodeId] = [
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


@dataclass(frozen=True)
class V4ProductionResult:
    run_manifest: Path
    final_video: Path | None
    final_cover: Path | None


def _artifact(run_dir: Path, rel: str) -> ProductionArtifact | None:
    path = run_dir / rel
    if not path.is_file():
        return None
    return ProductionArtifact(object_key=rel.replace("\\", "/"), content_sha256=sha256_file(path))


def _ffprobe_json(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr[-1000:]}")
    import json

    return json.loads(proc.stdout)


class V4ProductionOrchestrator:
    """Single V4 production DAG. Does not wrap or import V3 Orchestrator."""

    def __init__(self, context: RunContext) -> None:
        self.context = context
        self._stage = V4Orchestrator(context)

    def run(
        self,
        *,
        render: bool = True,
        allow_fake_derivation: bool = False,
        db: Path | None = None,
        object_root: Path | None = None,
        run_seed: str | None = None,
        sfx_profile_id: str = "normal",
        skip_ffmpeg: bool = False,
        until: str | None = None,
    ) -> V4ProductionResult:
        started = time.perf_counter()
        seed = run_seed or self.context.case.case_id
        nodes: dict[str, ProductionNodeManifest] = {}
        stop_at = until

        def _skip_remaining(after: str) -> None:
            seen = False
            for node_id in NODE_ORDER:
                if node_id == after:
                    seen = True
                    continue
                if not seen:
                    continue
                if node_id in nodes:
                    continue
                nodes[node_id] = ProductionNodeManifest(
                    node_id=node_id,  # type: ignore[arg-type]
                    status="skipped",
                    dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES[node_id]),
                    input_fingerprints={"until": sha256_json({"until": stop_at, "after": after})},
                    outputs=[],
                    elapsed_ms=0,
                )

        def _write_result(*, status: str, stopped: bool) -> V4ProductionResult:
            manifest = V4RunManifest(
                schema_version="v4.run_manifest.1",
                pipeline_version="v4",
                case_id=self.context.case.case_id.lower().replace(" ", "_"),
                run_id=self.context.run_id.lower(),
                status=status,  # type: ignore[arg-type]
                input_mode="script" if self.context.case.mode == "script_locked" else "goal",
                nodes=[nodes[node_id] for node_id in NODE_ORDER],
                deliverables=[
                    a
                    for a in (
                        _artifact(self.context.run_dir, "final/video.mp4"),
                        _artifact(self.context.run_dir, "final/cover.png"),
                    )
                    if a is not None
                ],
            )
            write_json_atomic(
                self.context.artifact("run_manifest.meta.json"),
                {
                    "registry_snapshot_id": self._registry_snapshot_id(),
                    "asset_snapshot_id": self._asset_snapshot_id(),
                    "until": stop_at,
                    "stopped_early": stopped,
                },
            )
            manifest_path = self.context.artifact("run_manifest.json")
            write_json_atomic(manifest_path, manifest)
            video = self.context.run_dir / "final" / "video.mp4"
            cover = self.context.run_dir / "final" / "cover.png"
            write_json_atomic(
                self.context.case_dir / "latest_run.json",
                {
                    "run_id": self.context.run_id,
                    "status": status,
                    "pipeline_version": "v4",
                    "completed_at": utc_now(),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                    "until": stop_at,
                    "stopped_early": stopped,
                    "final_video": "final/video.mp4" if video.is_file() else None,
                    "final_cover": "final/cover.png" if cover.is_file() else None,
                },
            )
            logger.info(
                "[V4][production] %s case=%s run=%s until=%s elapsed=%.2fs",
                "stopped" if stopped else "completed",
                self.context.case.case_id,
                self.context.run_id,
                stop_at,
                time.perf_counter() - started,
            )
            return V4ProductionResult(
                run_manifest=manifest_path,
                final_video=video if video.is_file() else None,
                final_cover=cover if cover.is_file() else None,
            )

        def _stop_after(checkpoint: str) -> bool:
            return stop_at == checkpoint

        # Stage1 covers narration → speech ∥ scope → scene (+ registry freeze).
        node_start = time.perf_counter()
        self._stage.run_stage1()
        for node_id in ("narration", "registry_voice", "speech", "scope", "scene"):
            outputs = []
            mapping = {
                "narration": "frozen_narration.json",
                "registry_voice": "resolved_voice_profile.json",
                "speech": "speech_timing_lock.json",
                "scope": "video_scope.json",
                "scene": "scene_semantic_plan.json",
            }
            art = _artifact(self.context.run_dir, mapping[node_id])
            if art:
                outputs.append(art)
            nodes[node_id] = ProductionNodeManifest(
                node_id=node_id,  # type: ignore[arg-type]
                status="completed",
                dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES[node_id]),
                input_fingerprints={"stage1": sha256_json({"run_id": self.context.run_id})},
                outputs=outputs,
                elapsed_ms=round((time.perf_counter() - node_start) * 1000),
            )
        if _stop_after("scene"):
            _skip_remaining("scene")
            return _write_result(status="completed", stopped=True)

        # assets
        t0 = time.perf_counter()
        self._stage.run_stage4(
            run_seed=seed,
            allow_fake_derivation=allow_fake_derivation,
            db=db,
            object_root=object_root,
        )
        nodes["assets"] = ProductionNodeManifest(
            node_id="assets",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["assets"]),
            outputs=[a for a in [_artifact(self.context.run_dir, "resolved_asset_plan.json")] if a],
            elapsed_ms=round((time.perf_counter() - t0) * 1000),
        )
        if _stop_after("assets"):
            _skip_remaining("assets")
            return _write_result(status="completed", stopped=True)

        # anchor
        t0 = time.perf_counter()
        self._stage.run_stage6(phase="anchor")
        nodes["anchor"] = ProductionNodeManifest(
            node_id="anchor",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["anchor"]),
            outputs=[a for a in [_artifact(self.context.run_dir, "anchored_timing_plan.json")] if a],
            elapsed_ms=round((time.perf_counter() - t0) * 1000),
        )
        if _stop_after("anchor"):
            _skip_remaining("anchor")
            return _write_result(status="completed", stopped=True)

        # motion_audio
        t0 = time.perf_counter()
        self._stage.run_stage5(run_seed=seed, sfx_profile_id=sfx_profile_id)
        nodes["motion_audio"] = ProductionNodeManifest(
            node_id="motion_audio",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["motion_audio"]),
            outputs=[a for a in [_artifact(self.context.run_dir, "motion_audio_plan.json")] if a],
            elapsed_ms=round((time.perf_counter() - t0) * 1000),
        )
        if _stop_after("motion_audio"):
            _skip_remaining("motion_audio")
            return _write_result(status="completed", stopped=True)

        # bgm (default disabled)
        nodes["bgm"] = self._run_bgm_node()

        # compile + optional render
        t0 = time.perf_counter()
        assets_root = object_root
        if assets_root is None:
            config_path = self.context.repo_root / "config" / "assets.v4.json"
            if config_path.is_file():
                assets_root = self.context.repo_root / load_json(config_path)["object_root"]
            else:
                assets_root = self.context.repo_root / "assets"
        do_render = bool(render) and not _stop_after("compile")
        stage6 = self._stage.run_stage6(
            phase="compile-render",
            object_root=assets_root,
            render=do_render,
            skip_ffmpeg=skip_ffmpeg,
        )
        nodes["compile"] = ProductionNodeManifest(
            node_id="compile",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["compile"]),
            outputs=[a for a in [_artifact(self.context.run_dir, "compiled_video_timeline.json")] if a],
            elapsed_ms=round((time.perf_counter() - t0) * 1000),
        )
        nodes["structured_qa"] = self._run_structured_qa()
        if _stop_after("compile"):
            _skip_remaining("structured_qa")
            return _write_result(status="completed", stopped=True)

        render_outputs = []
        for rel in ("render/silent.mp4", "render/final.mp4", "render/remotion.timeline.json"):
            art = _artifact(self.context.run_dir, rel)
            if art:
                render_outputs.append(art)
        nodes["render"] = ProductionNodeManifest(
            node_id="render",
            status="completed" if (not do_render or stage6.final_video) else "failed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["render"]),
            outputs=render_outputs,
            elapsed_ms=0,
            error_code=None if (not do_render or stage6.final_video) else "render_failed",
        )
        if nodes["render"].status == "failed":
            raise RuntimeError("render_failed: missing render/final.mp4")

        nodes["cover"] = self._run_cover_node()
        nodes["delivery_qa"] = self._run_delivery_qa()
        nodes["finalize"] = self._run_finalize()
        return _write_result(status="completed", stopped=False)

    def _registry_snapshot_id(self) -> str:
        path = self.context.artifact("capability_registry.snapshot.json")
        if not path.is_file():
            return "registry-snapshot://unknown"
        data = load_json(path)
        return str(data.get("snapshot_id") or f"registry-snapshot://sha256/{sha256_file(path)}")

    def _asset_snapshot_id(self) -> str:
        path = self.context.artifact("asset_repository.snapshot.json")
        if not path.is_file():
            return "asset-snapshot://unknown"
        data = load_json(path)
        return str(data.get("snapshot_id") or f"asset-snapshot://sha256/{sha256_file(path)}")

    def _run_bgm_node(self) -> ProductionNodeManifest:
        # Unit0 freezes bgm.enabled=false until a real profile exists.
        disabled = {
            "schema_version": "v4.bgm_disabled.1",
            "enabled": False,
            "reason": "no_registered_bgm_profile",
        }
        path = self.context.artifact("bgm_plan.json")
        write_json_atomic(path, disabled)
        return ProductionNodeManifest(
            node_id="bgm",
            status="skipped",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["bgm"]),
            input_fingerprints={"enabled": sha256_json({"enabled": False})},
            outputs=[ProductionArtifact(object_key="bgm_plan.json", content_sha256=sha256_file(path))],
            elapsed_ms=0,
        )

    def _run_structured_qa(self) -> ProductionNodeManifest:
        timeline = self.context.artifact("compiled_video_timeline.json")
        validation = self.context.artifact("stage6_validation.json")
        scene_plan = self.context.artifact("scene_semantic_plan.json")
        checks: list[QaCheck] = []
        if timeline.is_file():
            checks.append(
                QaCheck(
                    check_id="compiled_timeline_present",
                    status="pass",
                    hard=True,
                    message="compiled_video_timeline.json exists",
                    artifact_refs=["compiled_video_timeline.json"],
                )
            )
        else:
            checks.append(
                QaCheck(
                    check_id="compiled_timeline_present",
                    status="fail",
                    hard=True,
                    message="compiled_video_timeline.json missing",
                )
            )
        if validation.is_file():
            payload = load_json(validation)
            ok = bool(payload.get("ok", payload.get("passed", True)))
            checks.append(
                QaCheck(
                    check_id="stage6_validation",
                    status="pass" if ok else "fail",
                    hard=True,
                    message="stage6_validation aggregate",
                    artifact_refs=["stage6_validation.json"],
                )
            )
        checks.append(self._check_no_empty_visual_scenes(scene_plan))
        timeline_sha = sha256_file(timeline) if timeline.is_file() else ("0" * 64)
        report = StructuredQaReport(
            schema_version="v4.structured_qa.1",
            timeline_sha256=timeline_sha,
            passed=not any(c.hard and c.status == "fail" for c in checks),
            checks=checks,
        )
        report_path = self.context.artifact("structured_qa_report.json")
        write_json_atomic(report_path, report)
        if not report.passed:
            raise RuntimeError("structured_qa_failed")
        return ProductionNodeManifest(
            node_id="structured_qa",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["structured_qa"]),
            outputs=[ProductionArtifact(object_key="structured_qa_report.json", content_sha256=sha256_file(report_path))],
            elapsed_ms=0,
        )

    def _check_no_empty_visual_scenes(self, scene_plan: Path) -> QaCheck:
        if not scene_plan.is_file():
            return QaCheck(
                check_id="no_empty_visual_scenes",
                status="fail",
                hard=True,
                message="scene_semantic_plan.json missing; cannot verify empty-visual policy",
            )
        raw = load_json(scene_plan)
        payload = raw.get("payload") if isinstance(raw, dict) and "payload" in raw else raw
        scenes = sorted((payload or {}).get("scenes") or [], key=lambda item: int(item.get("order") or 0))
        empty_ids: list[str] = []
        for scene in scenes:
            slots = scene.get("slots") or []
            if (
                scene.get("no_asset")
                or scene.get("visual_structure") == "no_asset_transition"
                or not slots
            ):
                empty_ids.append(str(scene.get("scene_id") or "?"))
                continue
            # Non-CTA outro-only scenes are treated as empty fillers.
            text = str(scene.get("text") or "")
            only_outro = all(
                (slot.get("asset_role") == "outro"
                 and (slot.get("source") or {}).get("kind") == "configured_asset"
                 and (slot.get("source") or {}).get("config_key") == "default_outro")
                for slot in slots
            )
            if only_outro and not ("搜索" in text and ("柯幻" in text or "熊猫" in text)):
                empty_ids.append(str(scene.get("scene_id") or "?"))
        ok = not empty_ids
        return QaCheck(
            check_id="no_empty_visual_scenes",
            status="pass" if ok else "fail",
            hard=True,
            message=(
                "all scenes have result/site_home/hold-extend (or explicit search outro)"
                if ok
                else f"empty or unknown visuals remain: {', '.join(empty_ids)}"
            ),
            artifact_refs=["scene_semantic_plan.json"],
        )

    def _run_cover_node(self) -> ProductionNodeManifest:
        frozen = load_model(self.context.artifact("frozen_narration.json"), FrozenNarration)
        scope_env = load_json(self.context.artifact("video_scope.json"))
        scope_payload = scope_env.get("payload") if isinstance(scope_env, dict) else scope_env
        scope = VideoScope.model_validate(scope_payload)
        asset_plan_path = self.context.artifact("resolved_asset_plan.json")
        representative: list[str] = []
        if asset_plan_path.is_file():
            plan = load_json(asset_plan_path)
            for scene in plan.get("scenes") or []:
                for slot in scene.get("slots") or []:
                    ref = slot.get("asset_ref") or slot.get("selected_asset_ref")
                    if isinstance(ref, str) and ref.startswith("asset://A") and "result" in str(slot.get("asset_role") or ""):
                        representative.append(ref)
            representative = list(dict.fromkeys(representative))[:3]

        title = (self.context.case.goal or frozen.text[:28]).strip()[:28] or "功能介绍"
        brief = CoverBrief(
            schema_version="v4.cover_brief.1",
            narration_sha256=sha256_json({"text": frozen.text}),
            video_scope_sha256=sha256_json(scope.model_dump(mode="json")),
            full_narration_text=frozen.text,
            title=title,
            subtitle=None,
            representative_asset_refs=representative,
            brand_logo_object_key=_OFFICIAL_BRAND_LOGO,
            platform_profile_id="douyin_portrait_v1",
        )
        cover_dir = self.context.run_dir / "cover"
        cover_dir.mkdir(parents=True, exist_ok=True)
        brief_path = cover_dir / "cover_brief.json"
        write_json_atomic(brief_path, brief)

        logo = self.context.repo_root / _OFFICIAL_BRAND_LOGO
        cover_png = cover_dir / "cover.png"
        self._render_cover_png(brief=brief, logo_path=logo if logo.is_file() else None, output=cover_png)
        return ProductionNodeManifest(
            node_id="cover",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["cover"]),
            outputs=[
                ProductionArtifact(object_key="cover/cover_brief.json", content_sha256=sha256_file(brief_path)),
                ProductionArtifact(object_key="cover/cover.png", content_sha256=sha256_file(cover_png)),
            ],
            elapsed_ms=0,
        )

    def _render_cover_png(self, *, brief: CoverBrief, logo_path: Path | None, output: Path) -> None:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (1080, 1920), color=(18, 22, 28))
        draw = ImageDraw.Draw(image)
        try:
            font_title = ImageFont.truetype("msyh.ttc", 72)
            font_body = ImageFont.truetype("msyh.ttc", 36)
        except OSError:
            font_title = ImageFont.load_default()
            font_body = font_title
        draw.text((80, 220), brief.title[:28], fill=(245, 245, 240), font=font_title)
        body = brief.full_narration_text[:120]
        draw.text((80, 360), body, fill=(200, 200, 195), font=font_body)
        if logo_path and logo_path.is_file():
            with Image.open(logo_path) as logo:
                logo = logo.convert("RGBA")
                logo.thumbnail((280, 280))
                image.paste(logo, (80, 1500), logo)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG")

    def _run_delivery_qa(self) -> ProductionNodeManifest:
        video = self.context.run_dir / "render" / "final.mp4"
        cover = self.context.run_dir / "cover" / "cover.png"
        checks: list[QaCheck] = []
        if video.is_file():
            probe = _ffprobe_json(video)
            streams = probe.get("streams") or []
            has_video = any(s.get("codec_type") == "video" for s in streams)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            checks.append(
                QaCheck(
                    check_id="video_decodable",
                    status="pass" if has_video else "fail",
                    hard=True,
                    message="video stream present",
                    artifact_refs=["render/final.mp4"],
                )
            )
            checks.append(
                QaCheck(
                    check_id="audio_present",
                    status="pass" if has_audio else "fail",
                    hard=True,
                    message="audio stream present",
                    artifact_refs=["render/final.mp4"],
                )
            )
        else:
            checks.append(
                QaCheck(check_id="video_decodable", status="fail", hard=True, message="render/final.mp4 missing")
            )
        checks.append(
            QaCheck(
                check_id="cover_independent",
                status="pass" if cover.is_file() else "fail",
                hard=True,
                message="cover.png exists as independent deliverable (not prepended)",
                artifact_refs=["cover/cover.png"],
            )
        )
        report = DeliveryQaReport(
            schema_version="v4.delivery_qa.1",
            video_object_key="render/final.mp4",
            cover_object_key="cover/cover.png",
            passed=not any(c.hard and c.status == "fail" for c in checks),
            checks=checks,
        )
        report_path = self.context.artifact("delivery_qa_report.json")
        write_json_atomic(report_path, report)
        if not report.passed:
            raise RuntimeError("delivery_qa_failed")
        return ProductionNodeManifest(
            node_id="delivery_qa",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["delivery_qa"]),
            outputs=[ProductionArtifact(object_key="delivery_qa_report.json", content_sha256=sha256_file(report_path))],
            elapsed_ms=0,
        )

    def _run_finalize(self) -> ProductionNodeManifest:
        final_dir = self.context.run_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        src_video = self.context.run_dir / "render" / "final.mp4"
        src_cover = self.context.run_dir / "cover" / "cover.png"
        dst_video = final_dir / "video.mp4"
        dst_cover = final_dir / "cover.png"
        if not src_video.is_file():
            raise RuntimeError("finalization_failed: missing render/final.mp4")
        if not src_cover.is_file():
            raise RuntimeError("finalization_failed: missing cover/cover.png")
        shutil.copy2(src_video, dst_video)
        shutil.copy2(src_cover, dst_cover)
        return ProductionNodeManifest(
            node_id="finalize",
            status="completed",
            dependency_node_ids=list(PRODUCTION_DAG_DEPENDENCIES["finalize"]),
            outputs=[
                ProductionArtifact(object_key="final/video.mp4", content_sha256=sha256_file(dst_video)),
                ProductionArtifact(object_key="final/cover.png", content_sha256=sha256_file(dst_cover)),
            ],
            elapsed_ms=0,
        )
