from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from video_agent.ai.story_planner import plan_narration
from video_agent.ai.visual_planner import plan_visual
from video_agent.ai.visual_critic import review_contact_sheet
from video_agent.assets import build_catalog, catalog_snapshot, materialize_assets
from video_agent.compiler import compile_render_plan
from video_agent.contracts import AssetCatalog, MaterializationPlan, Narration, QaReport, RenderPlan, TimingLock, VisualPlan
from video_agent.io import load_json, load_model, sha256_file, sha256_json, utc_now, write_json_atomic
from video_agent.planning import build_auto_visual_plan
from video_agent.qa import run_final_qa, validate_render_plan, validate_timing_lock
from video_agent.render import render_video
from video_agent.runtime import RunContext, STAGES
from video_agent.speech import MinimaxClient, build_timing_lock


class Orchestrator:
    def __init__(self, context: RunContext) -> None:
        self.context = context
        manifest_path = self.context.artifact("run_manifest.json")
        if manifest_path.is_file():
            loaded = load_json(manifest_path)
            if not isinstance(loaded, dict) or loaded.get("case_id") != context.case.case_id or loaded.get("run_id") != context.run_id:
                raise ValueError("existing run_manifest does not match the requested case/run")
            self.manifest = loaded
            self.manifest.setdefault("stages", {})
            self.manifest.setdefault("prompts", [])
            self.manifest["status"] = "running"
            self.manifest.pop("error", None)
        else:
            self.manifest = {
            "schema_version": 3,
            "case_id": context.case.case_id,
            "run_id": context.run_id,
            "created_at": utc_now(),
            "status": "running",
            "stages": {},
            "prompts": [],
            }

    def _record(
        self,
        stage: str,
        status: str,
        output: Path | None = None,
        details: dict[str, Any] | None = None,
        input_sha256: str | None = None,
        input_fingerprint: dict[str, Any] | None = None,
    ) -> None:
        item: dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if input_sha256:
            item["input_sha256"] = input_sha256
        if input_fingerprint:
            item["input_fingerprint"] = input_fingerprint
        if output and output.is_file():
            item.update({"output": output.as_posix(), "sha256": sha256_file(output)})
        if details:
            item["details"] = details
        self.manifest["stages"][stage] = item
        write_json_atomic(self.context.artifact("run_manifest.json"), self.manifest)

    def _artifact_sha256(self, name: str) -> str | None:
        path = self.context.artifact(name)
        return sha256_file(path) if path.is_file() else None

    def _content_sha256(self, path: Path | None) -> str | None:
        return sha256_file(path) if path and path.is_file() else None

    def _source_sha256(self, source: str | None) -> str | None:
        return self._content_sha256(self.context.case_dir / source) if source else None

    def _code_fingerprint(self) -> str:
        paths = sorted((self.context.repo_root / "video_agent").rglob("*.py"))
        paths.extend(sorted((self.context.repo_root / "video_agent" / "prompts").rglob("*.md")))
        return sha256_json(
            [{"path": path.relative_to(self.context.repo_root).as_posix(), "sha256": sha256_file(path)} for path in paths]
        )

    def _provider_fingerprint(self) -> dict[str, str]:
        config_path = self.context.repo_root / "config" / "ai.local.json"
        config = load_json(config_path) if config_path.is_file() else {}
        return {
            "provider": "openai_compatible",
            "base_url": str(os.getenv("VIDEO_AGENT_AI_BASE_URL") or config.get("base_url") or "").rstrip("/"),
            "model": str(config.get("model") or "gpt-5"),
        }

    def _stage_input_fingerprint(self, stage: str) -> dict[str, Any]:
        case = self.context.case.model_dump(mode="json")
        prompt_map = {
            "materialize": "materialization/controlled_derivative.md",
            "narration": "story_and_shot_proposal.md",
            "visual": "visual_story_planner.md",
            "qa": "visual_critic.md",
        }
        prompt_name = prompt_map.get(stage)
        prompt_sha = self._content_sha256(self.context.repo_root / "video_agent" / "prompts" / prompt_name) if prompt_name else None
        common = {
            "code_sha256": self._code_fingerprint(),
            "prompt_sha256": prompt_sha,
            "provider": self._provider_fingerprint(),
            "vision_review_enabled": self.context.case.vision_review_enabled,
            "quality": self.context.case.quality,
        }
        source_map: dict[str, Any] = {
            "catalog": {
                "case": case,
                "global_catalog": sha256_file(self.context.repo_root / "assets" / "catalog.json")
                if (self.context.repo_root / "assets" / "catalog.json").is_file()
                else None,
            },
            "materialize": {"case": case, "catalog": self._artifact_sha256("asset_catalog.source.json"), "source": self._source_sha256(self.context.case.materialization_source)},
            "narration": {"case": case, "catalog": self._artifact_sha256("asset_catalog.json"), "source": self._source_sha256(self.context.case.narration_source)},
            "speech": {"voice": case["voice"], "narration": self._artifact_sha256("narration.json")},
            "visual": {
                "mode": case["visual_planner_mode"],
                "narration": self._artifact_sha256("narration.json"),
                "timing": self._artifact_sha256("timing_lock.json"),
                "catalog": self._artifact_sha256("asset_catalog.json"),
                "source": self._source_sha256(self.context.case.visual_plan_source),
            },
            "compile": {
                "narration": self._artifact_sha256("narration.json"),
                "timing": self._artifact_sha256("timing_lock.json"),
                "visual": self._artifact_sha256("visual_plan.json"),
                "catalog": self._artifact_sha256("asset_catalog.json"),
                "format": case["format"],
                "audio": case["audio"],
            },
            "render": {"plan": self._artifact_sha256("render_plan.json"), "quality": case["quality"]},
            "qa": {"plan": self._artifact_sha256("render_plan.json"), "video": self._artifact_sha256("final/video.mp4"), "vision_review_enabled": case["vision_review_enabled"]},
        }
        return {**common, "stage": stage, "inputs": source_map[stage]}

    def _stage_input_sha256(self, stage: str) -> str:
        return sha256_json(self._stage_input_fingerprint(stage))

    def _can_resume_stage(self, stage: str, input_sha256: str) -> bool:
        item = self.manifest["stages"].get(stage)
        if not isinstance(item, dict) or item.get("status") != "completed" or item.get("input_sha256") != input_sha256:
            return False
        output = item.get("output")
        expected = item.get("sha256")
        path = Path(str(output)) if output else None
        return bool(path and expected and path.is_file() and sha256_file(path) == expected)

    def run(self, from_stage: str | None = None, until_stage: str | None = None) -> Path | None:
        start = STAGES.index(from_stage) if from_stage else 0
        end = STAGES.index(until_stage) if until_stage else len(STAGES) - 1
        if start > end:
            raise ValueError("from-stage must not come after until-stage")
        existing_video = self.context.run_dir / "final" / "video.mp4"
        final_video: Path | None = existing_video if existing_video.is_file() else None
        stage = "unknown"
        input_sha256: str | None = None
        input_fingerprint: dict[str, Any] | None = None
        try:
            for stage in STAGES[start : end + 1]:
                input_fingerprint = self._stage_input_fingerprint(stage)
                input_sha256 = sha256_json(input_fingerprint)
                if from_stage is None and self._can_resume_stage(stage, input_sha256):
                    continue
                method = getattr(self, f"stage_{stage}")
                output = method()
                self._record(stage, "completed", output if isinstance(output, Path) else None, input_sha256=input_sha256, input_fingerprint=input_fingerprint)
                if stage == "render" and isinstance(output, Path):
                    final_video = output
            self.manifest["status"] = "completed"
            write_json_atomic(self.context.artifact("run_manifest.json"), self.manifest)
            self.context.mark_latest("completed", final_video.as_posix() if final_video else None)
            return final_video
        except Exception as exc:
            self.manifest["status"] = "failed"
            self.manifest["error"] = {"type": exc.__class__.__name__, "message": str(exc)}
            self._record(stage, "failed", details={"type": exc.__class__.__name__, "message": str(exc)}, input_sha256=input_sha256, input_fingerprint=input_fingerprint)
            self.context.mark_latest("failed")
            raise

    def stage_catalog(self) -> Path:
        global_path = self.context.repo_root / "assets" / "catalog.json"
        if global_path.is_file():
            catalog = load_model(global_path, AssetCatalog)
        else:
            catalog = build_catalog(self.context.repo_root / "assets", global_path)
        snapshot = catalog_snapshot(catalog, self.context.case.feature_path, self.context.case.selected_asset_ids)
        output = self.context.artifact("asset_catalog.source.json")
        write_json_atomic(output, snapshot)
        return output

    def stage_materialize(self) -> Path:
        source = load_model(self.context.artifact("asset_catalog.source.json"), AssetCatalog)
        if self.context.case.materialization_source:
            plan = load_model(self.context.case_dir / self.context.case.materialization_source, MaterializationPlan)
            if plan.case_id != self.context.case.case_id:
                raise ValueError("materialization plan case_id differs from case.json")
            catalog = materialize_assets(self.context.repo_root, source, plan, self.context.run_dir / "work" / "derived_assets")
        else:
            catalog = source
        output = self.context.artifact("asset_catalog.json")
        write_json_atomic(output, catalog)
        return output

    def stage_narration(self) -> Path:
        catalog = load_model(self.context.artifact("asset_catalog.json"), AssetCatalog)
        if self.context.case.narration_source:
            narration = load_model(self.context.case_dir / self.context.case.narration_source, Narration)
        elif self.context.case.ai_enabled:
            narration, prompt = plan_narration(self.context.repo_root, self.context.case, catalog)
            self.manifest["prompts"].append(prompt)
        else:
            raise ValueError("case requires narration_source when ai_enabled=false")
        if narration.case_id != self.context.case.case_id:
            raise ValueError("narration case_id differs from case.json")
        output = self.context.artifact("narration.json")
        write_json_atomic(output, narration)
        return output

    def stage_speech(self) -> Path:
        narration = load_model(self.context.artifact("narration.json"), Narration)
        result = MinimaxClient(self.context.repo_root).synthesize(self.context.case, narration, self.context.run_dir / "work" / "speech")
        timing = build_timing_lock(
            self.context.case.case_id,
            narration,
            result.tokens,
            result.audio_path,
            result.duration_ms,
            self.context.case.format.fps,
        )
        timing_checks = validate_timing_lock(narration, timing)
        failures = [check for check in timing_checks if check.status == "failed"]
        write_json_atomic(
            self.context.artifact("timing_qa.json"),
            {"checks": [check.model_dump(mode="json") for check in timing_checks]},
        )
        if failures:
            raise ValueError("timing lock failed validation: " + "; ".join(item.check_id for item in failures))
        output = self.context.artifact("timing_lock.json")
        write_json_atomic(output, timing)
        return output

    def stage_visual(self) -> Path:
        narration = load_model(self.context.artifact("narration.json"), Narration)
        timing = load_model(self.context.artifact("timing_lock.json"), TimingLock)
        catalog = load_model(self.context.artifact("asset_catalog.json"), AssetCatalog)
        if self.context.case.visual_plan_source:
            visual = load_model(self.context.case_dir / self.context.case.visual_plan_source, VisualPlan)
        elif self.context.case.visual_planner_mode == "multimodal":
            visual, prompt = plan_visual(self.context.repo_root, self.context.case, narration, timing, catalog)
            self.manifest["prompts"].append(prompt)
        else:
            visual = build_auto_visual_plan(self.context.case.case_id, narration, timing, catalog)
        visual.timing_lock_sha256 = sha256_json(timing)
        output = self.context.artifact("visual_plan.json")
        write_json_atomic(output, visual)
        return output

    def stage_compile(self) -> Path:
        narration = load_model(self.context.artifact("narration.json"), Narration)
        timing = load_model(self.context.artifact("timing_lock.json"), TimingLock)
        visual = load_model(self.context.artifact("visual_plan.json"), VisualPlan)
        catalog = load_model(self.context.artifact("asset_catalog.json"), AssetCatalog)
        plan = compile_render_plan(
            self.context.case.case_id,
            self.context.run_id,
            narration,
            timing,
            visual,
            catalog,
            self.context.repo_root,
            self.context.case.platform_profile,
            self.context.case.format.width,
            self.context.case.format.height,
            self.context.case_dir,
            self.context.case.audio,
            self.context.case.duration_policy,
        )
        checks = validate_render_plan(plan)
        failures = [check for check in checks if check.status == "failed"]
        if failures:
            raise ValueError("render plan failed validation: " + "; ".join(f"{item.check_id}:{item.message}" for item in failures))
        output = self.context.artifact("render_plan.json")
        write_json_atomic(output, plan)
        return output

    def stage_render(self) -> Path:
        plan = load_model(self.context.artifact("render_plan.json"), RenderPlan)
        output = self.context.run_dir / "final" / "video.mp4"
        return render_video(plan, output, preset="veryfast" if self.context.case.quality == "draft" else "medium", crf=22 if self.context.case.quality == "draft" else 18)

    def stage_qa(self) -> Path:
        plan = load_model(self.context.artifact("render_plan.json"), RenderPlan)
        video = self.context.run_dir / "final" / "video.mp4"
        report: QaReport = run_final_qa(plan, video, self.context.run_dir)
        if self.context.case.vision_review_enabled:
            review, trace = review_contact_sheet(
                self.context.repo_root,
                plan,
                self.context.run_dir / "final" / "contact_sheet.jpg",
                sorted((self.context.run_dir / "final").glob("cue_contact_sheet_*.jpg")),
            )
            report.checks.append(review)
            self.manifest["prompts"].append({"path": trace["path"], "sha256": trace["sha256"]})
            write_json_atomic(self.context.artifact("vision_review.json"), trace["result"])
            if review.status == "failed":
                report.status = "failed"
        output = self.context.artifact("qa_report.json")
        write_json_atomic(output, report)
        if report.status != "passed":
            failures = [item.check_id for item in report.checks if item.status == "failed"]
            raise ValueError(f"final video QA failed: {', '.join(failures)}")
        return output
