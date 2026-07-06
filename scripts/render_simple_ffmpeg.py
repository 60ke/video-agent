import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from utils.case_guards import kehuanxiongmao_auth_errors

DEFAULT_SUBTITLE_FONT_NAME = "Noto Sans CJK SC"


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return case_dir / path


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ffprobe_duration(path: Path) -> float | None:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def append_outro(case_dir: Path, main_output: Path, final_output: Path, ending_track: dict[str, Any]) -> bool:
    if ending_track.get("policy") not in ("default", "custom"):
        if main_output != final_output:
            final_output.write_bytes(main_output.read_bytes())
        return False

    outro = resolve_case_path(case_dir, ending_track.get("source"))
    if not outro or not outro.is_file():
        raise FileNotFoundError(f"ending video missing: {ending_track.get('source')}")

    temp_dir = final_output.parent / "_concat"
    temp_dir.mkdir(parents=True, exist_ok=True)
    main_norm = temp_dir / f"{final_output.stem}_main_norm.mp4"
    outro_norm = temp_dir / f"{final_output.stem}_outro_norm.mp4"
    concat_list = temp_dir / f"{final_output.stem}_concat.txt"

    for src, dst in ((main_output, main_norm), (outro, outro_norm)):
        proc = run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-vf",
                "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-shortest",
                str(dst),
            ],
            case_dir,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg normalize failed:\n{proc.stderr[-4000:]}")

    concat_list.write_text(
        f"file '{main_norm.as_posix()}'\nfile '{outro_norm.as_posix()}'\n",
        encoding="utf-8",
    )
    proc = run_command(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart", str(final_output)],
        case_dir,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg outro concat failed:\n{proc.stderr[-4000:]}")
    return True


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    if centiseconds >= 100:
        secs += 1
        centiseconds = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def escape_ass_text(text: str) -> str:
    return text.replace("{", r"\{").replace("}", r"\}")


def escape_filter_path(path: Path) -> str:
    return path.as_posix().replace("\\", "\\\\").replace("'", r"\\'")


def text_units(text: str) -> int:
    return max(len("".join(str(text).split())), 1)


def split_subtitle_text(text: str, max_chars: int) -> list[str]:
    compact = " ".join(str(text).strip().split())
    if not compact:
        return []
    if len(compact) <= max_chars:
        return [compact]

    chunks: list[str] = []
    current = ""
    break_chars = set("，。！？；、,.!?; ")
    for char in compact:
        if current and len(current) + 1 > max_chars:
            chunks.append(current.strip())
            current = ""
        current += char
        if len(current) >= max_chars or (len(current) >= max_chars - 4 and char in break_chars):
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def split_subtitle_segment(seg: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    start = float(seg.get("start", 0))
    end = float(seg.get("end", start + 1))
    chunks = split_subtitle_text(str(seg.get("text", "")), max_chars)
    if not chunks:
        return []
    if len(chunks) == 1:
        return [{"start": start, "end": end, "text": chunks[0]}]

    duration = max(end - start, 0.001)
    total_weight = sum(text_units(chunk) for chunk in chunks)
    cursor = start
    cues: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        chunk_end = end if idx == len(chunks) - 1 else cursor + duration * text_units(chunk) / total_weight
        cues.append({"start": cursor, "end": chunk_end, "text": chunk})
        cursor = chunk_end
    return cues


def fix_cjk_punctuation_wrap(lines: list[str]) -> list[str]:
    if len(lines) <= 1:
        return lines
    fixed: list[str] = [lines[0]]
    punctuation = "，。！？、；：,.!?:;"
    for line in lines[1:]:
        current = line
        while current and current[0] in punctuation:
            fixed[-1] += current[0]
            current = current[1:]
        if current:
            fixed.append(current)
    return fixed


def wrap_ass_subtitle_text(text: str, max_chars_per_line: int) -> str:
    normalized = " ".join(str(text).replace("\n", " ").split())
    if len(normalized) <= max_chars_per_line:
        return normalized
    lines = [
        normalized[start : start + max_chars_per_line]
        for start in range(0, len(normalized), max_chars_per_line)
    ]
    lines = fix_cjk_punctuation_wrap(lines)
    if len(lines) > 2:
        lines = lines[:2]
        lines[-1] = lines[-1].rstrip("，。,. ") + "..."
    return r"\N".join(lines)


def subtitle_style(width: int, height: int, font_size_override: int | None) -> dict[str, int]:
    font_size = font_size_override or max(32, min(84, int(height * 0.041)))
    margin_h = max(40, int(width * 0.105))
    margin_v = max(64, int(height * 0.25))
    outline = max(3, int(font_size * 0.085))
    shadow = max(1, int(font_size * 0.018))
    safe_text_width = width - margin_h * 2
    max_chars_per_line = max(7, min(11, int(safe_text_width / max(30, font_size * 0.95))))
    return {
        "font_size": font_size,
        "margin_h": margin_h,
        "margin_v": margin_v,
        "outline": outline,
        "shadow": shadow,
        "max_chars_per_line": max_chars_per_line,
        "cue_max_chars": max_chars_per_line * 2,
    }


def build_ass(
    project: dict[str, Any],
    ass_path: Path,
    *,
    width: int,
    height: int,
    font_name: str,
    font_size_override: int | None,
) -> dict[str, Any]:
    style = subtitle_style(width, height, font_size_override)
    track = project.get("subtitle_track", {})
    segments = track.get("segments", []) if isinstance(track, dict) else []

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{font_name},{style['font_size']},&H00FFFFFF,&H000000FF,"
            f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},"
            f"2,{style['margin_h']},{style['margin_h']},{style['margin_v']},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    cue_count = 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        for cue in split_subtitle_segment(seg, style["cue_max_chars"]):
            wrapped = wrap_ass_subtitle_text(cue["text"], style["max_chars_per_line"])
            lines.append(
                "Dialogue: 0,"
                f"{ass_time(cue['start'])},{ass_time(cue['end'])},"
                f"Default,,0,0,0,,{escape_ass_text(wrapped)}"
            )
            cue_count += 1

    ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return style | {"cue_count": cue_count, "font_name": font_name}


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = project.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("project.assets must be a list")
    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if isinstance(asset, dict) and asset.get("id"):
            result[str(asset["id"])] = asset
    return result


def extract_video_frame(src: Path, dst: Path) -> Path:
    proc = run_command(
        ["ffmpeg", "-y", "-i", str(src), "-frames:v", "1", str(dst)],
        dst.parent,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to extract video frame from {src}:\n{proc.stderr[-2000:]}")
    return dst


def open_visual_asset(src: Path, temp_dir: Path, idx: int) -> Image.Image:
    if src.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
        src = extract_video_frame(src, temp_dir / f"video_asset_{idx:03d}.png")
    return Image.open(src).convert("RGB")


def fit_width_on_canvas(image: Image.Image, width: int, height: int, *, color: tuple[int, int, int] = (8, 10, 12)) -> Image.Image:
    canvas = Image.new("RGB", (width, height), color)
    scale = width / image.width
    resized = image.resize((width, max(1, int(round(image.height * scale)))), Image.Resampling.LANCZOS)
    if resized.height <= height:
        y = (height - resized.height) // 2
        canvas.paste(resized, (0, y))
    else:
        top = (resized.height - height) // 2
        canvas.paste(resized.crop((0, top, width, top + height)), (0, 0))
    return canvas


def grid_on_canvas(images: list[Image.Image], width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (8, 10, 12))
    gap = 28
    safe_top = 120
    safe_bottom = 300
    work_h = height - safe_top - safe_bottom
    count = min(len(images), 4)
    if count <= 1:
        return fit_width_on_canvas(images[0], width, height)
    cols = 2
    rows = 1 if count == 2 else 2
    cell_w = (width - gap * (cols + 1)) // cols
    cell_h = (work_h - gap * (rows + 1)) // rows
    for idx, image in enumerate(images[:count]):
        row = idx // cols
        col = idx % cols
        tile = ImageOps.contain(image, (cell_w, cell_h), method=Image.Resampling.LANCZOS)
        x = gap + col * (cell_w + gap) + (cell_w - tile.width) // 2
        y = safe_top + gap + row * (cell_h + gap) + (cell_h - tile.height) // 2
        canvas.paste(tile, (x, y))
    return canvas


def render_event_frame(
    case_dir: Path,
    event: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    frame_path: Path,
    temp_dir: Path,
    width: int,
    height: int,
    idx: int,
) -> None:
    asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
    if not asset_ids:
        raise ValueError(f"visual event missing asset_ids: {event.get('id') or idx}")

    images: list[Image.Image] = []
    for asset_id in asset_ids[:4]:
        asset = assets.get(asset_id)
        if not asset:
            continue
        src = resolve_case_path(case_dir, asset.get("source"))
        if src and src.is_file():
            images.append(open_visual_asset(src, temp_dir, idx))
    if not images:
        raise FileNotFoundError(f"no renderable asset for visual event: {event.get('id') or idx}")

    layout = str(event.get("display_mode") or event.get("layout") or "").lower()
    if len(images) > 1 or layout in {"grid-rebuild", "main-plus-reference"}:
        frame = grid_on_canvas(images, width, height)
    else:
        frame = fit_width_on_canvas(images[0], width, height)
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(frame_path)


def build_concat_file(case_dir: Path, project: dict[str, Any], concat_path: Path, temp_dir: Path, width: int, height: int) -> list[dict[str, Any]]:
    assets = asset_index(project)
    lines = []
    rendered_events: list[dict[str, Any]] = []
    last_file = None
    previous_end = 0.0
    
    for idx, event in enumerate(project.get("visual_track", []), start=1):
        if not isinstance(event, dict):
            continue
            
        end = float(event.get("end", previous_end + 1))
        if end <= previous_end:
            continue
        duration = max(end - previous_end, 0.1)
        previous_end = end

        frame_path = temp_dir / "frames" / f"event_{idx:03d}.png"
        render_event_frame(case_dir, event, assets, frame_path, temp_dir, width, height, idx)
        abs_src = frame_path.resolve(strict=False).as_posix()
        
        lines.append(f"file '{abs_src}'")
        lines.append(f"duration {duration:.3f}")
        last_file = abs_src
        rendered_events.append(
            {
                "event_id": event.get("id") or f"visual_track[{idx - 1}]",
                "frame": str(frame_path),
                "duration": round(duration, 3),
                "layout": event.get("display_mode") or event.get("layout"),
                "asset_ids": event.get("asset_ids", []),
            }
        )
        
    if last_file:
        # FFmpeg concat demuxer requirement: the last file needs to be repeated without duration
        # to ensure the final frame is rendered properly up to the duration of the video.
        lines.append(f"file '{last_file}'")
        
    if not lines:
        raise ValueError("visual_track produced no renderable frames")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rendered_events


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path)
    input_data = load_json(case_dir / "input.json") if (case_dir / "input.json").is_file() else project.get("inputs", {})
    auth_errors = kehuanxiongmao_auth_errors(case_dir, input_data if isinstance(input_data, dict) else {})
    if auth_errors:
        raise ValueError("; ".join(auth_errors))
    
    label = args.label or datetime.now().strftime("simple_%Y%m%d_%H%M%S")
    versions_dir = case_dir / "output" / "versions"
    temp_dir = case_dir / "output" / "ffmpeg_temp"
    reports_dir = case_dir / "output" / "reports"
    versions_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    final_output = versions_dir / f"{label}.mp4"
    main_output = versions_dir / f"{label}_main.mp4"
    ass_path = temp_dir / "subs.ass"
    concat_path = temp_dir / "concat.txt"
    
    meta = project.get("meta", {})
    width = int(meta.get("width", 1080)) if isinstance(meta, dict) else 1080
    height = int(meta.get("height", 1920)) if isinstance(meta, dict) else 1920

    # 1. Build ASS subtitles and render per-event frames for the concat file.
    subtitle_style_report = build_ass(
        project,
        ass_path,
        width=width,
        height=height,
        font_name=args.subtitle_font_name,
        font_size_override=args.subtitle_font_size,
    )
    rendered_events = build_concat_file(case_dir, project, concat_path, temp_dir, width, height)

    # 2. Get Voice Audio
    voice = project.get("voice_track", {})
    audio_path = voice.get("audio_path") if isinstance(voice, dict) else None
    audio_src = resolve_case_path(case_dir, audio_path)
    if not audio_src or not audio_src.is_file():
        audio_src = case_dir / "audio" / "voice.mp3"
        if not audio_src.is_file():
            raise FileNotFoundError("Voice audio file not found")
            
    rel_audio_src = audio_src.relative_to(case_dir).as_posix()
    rel_ass = ass_path.relative_to(case_dir)
    rel_concat = concat_path.relative_to(case_dir).as_posix()
    rel_main_output = main_output.relative_to(case_dir).as_posix()
    
    # Subtitles escaping in FFmpeg can be tricky on Windows.
    # We use a simple force_style, and relative path to srt
    # For Windows ffmpeg, colon in paths within filters is extremely problematic, 
    # so running from case_dir with pure relative paths is safest.
    
    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[vbg];"
        f"[vbg]ass='{escape_filter_path(rel_ass)}'[vout]"
    )
    
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", rel_concat,
        "-i", rel_audio_src,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        rel_main_output
    ]
    
    print(f"Running FFmpeg: {' '.join(cmd)}", file=sys.stderr)
    
    proc = run_command(cmd, case_dir)
    
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{proc.stderr[-4000:]}")

    appended_outro = False
    if args.skip_outro:
        final_output.write_bytes(main_output.read_bytes())
    else:
        ending_track = project.get("ending_track", {})
        appended_outro = append_outro(case_dir, main_output, final_output, ending_track if isinstance(ending_track, dict) else {})

    report = {
        "schema_version": 1,
        "renderer": "simple_ffmpeg",
        "label": label,
        "case_dir": str(case_dir),
        "project": str(project_path),
        "main_output": str(main_output),
        "final_output": str(final_output),
        "main_duration": ffprobe_duration(main_output),
        "final_duration": ffprobe_duration(final_output),
        "outro_appended": appended_outro,
        "ass": str(ass_path),
        "subtitle_style": subtitle_style_report,
        "concat": str(concat_path),
        "rendered_events": rendered_events,
        "command": cmd,
    }
    report_path = reports_dir / f"{label}_render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "main_output": str(main_output),
            "final_output": str(final_output),
            "report": str(report_path),
        }
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a Pipeline V2 video with FFmpeg.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project", help="Project JSON path. Defaults to <case>/video_project.json.")
    parser.add_argument("--label")
    parser.add_argument("--skip-outro", action="store_true")
    parser.add_argument("--subtitle-font-name", default=DEFAULT_SUBTITLE_FONT_NAME)
    parser.add_argument("--subtitle-font-size", type=int, help="Override ASS subtitle font size. Defaults to height-based smartclip style.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }

    if args.json:
        sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    elif output["ok"]:
        print(f"Final video (Simple FFmpeg): {output['data']['final_output']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
