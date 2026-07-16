from pathlib import Path

from video_agent.case_admin import clean_cases, export_case_videos


def test_export_then_clean_cases(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    case = cases / "demo"
    video = case / "runs" / "run_001" / "final" / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"demo video")
    destination = tmp_path / "Videos"

    exported = export_case_videos(cases, destination)
    assert exported["videos"] == 1
    manifest = Path(str(exported["manifest"]))
    assert (destination / "demo.mp4").read_bytes() == b"demo video"
    cleaned = clean_cases(cases, require_export_manifest=manifest)
    assert cleaned["removed_cases"] == 1
    assert not case.exists()
