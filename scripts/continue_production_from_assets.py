"""Continue a Stage7 acceptance run after Stage1 artifacts already exist."""

from __future__ import annotations

import argparse
from pathlib import Path

from video_agent.progress import configure_logging, get_logger
from video_agent.runtime import RunContext
from video_agent.v4.orchestrator import V4Orchestrator
from video_agent.v4.production import V4ProductionOrchestrator


logger = get_logger()


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--resume", required=True)
    parser.add_argument("--seed", default=None)
    parser.add_argument("--from-stage", choices=("assets", "motion", "compile"), default="assets")
    args = parser.parse_args()
    context = RunContext.open(Path(args.case).resolve(), args.resume)
    stage = V4Orchestrator(context)
    seed = args.seed or context.case.case_id
    start = args.from_stage

    if start == "assets":
        logger.info("[V4][continue] stage4 case=%s run=%s", context.case.case_id, context.run_id)
        stage.run_stage4(run_seed=seed, allow_fake_derivation=False)
        start = "motion"
    if start == "motion":
        logger.info("[V4][continue] stage5")
        stage.run_stage5(run_seed=seed, sfx_profile_id="normal")
        start = "compile"
    if start == "compile":
        logger.info("[V4][continue] stage6 compile-render")
        stage.run_stage6(
            phase="compile-render",
            object_root=context.repo_root / "assets",
            render=True,
            skip_ffmpeg=False,
        )

    production = V4ProductionOrchestrator(context)
    logger.info("[V4][continue] structured_qa/cover/delivery/finalize")
    production._run_structured_qa()
    production._run_cover_node()
    production._run_delivery_qa()
    production._run_finalize()
    final_video = context.run_dir / "final" / "video.mp4"
    final_cover = context.run_dir / "final" / "cover.png"
    print(
        {
            "ok": final_video.is_file() and final_cover.is_file(),
            "final_video": final_video.as_posix() if final_video.is_file() else None,
            "final_cover": final_cover.as_posix() if final_cover.is_file() else None,
            "run_dir": context.run_dir.as_posix(),
        }
    )
    return 0 if final_video.is_file() and final_cover.is_file() else 2


if __name__ == "__main__":
    raise SystemExit(main())
