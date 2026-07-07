import argparse
import json
import subprocess
import sys
from bisect import bisect_right
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


def load_optional_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


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


RECORDING_LAYOUTS = {"browser-recording", "browser-recording-fit-width"}


def ffprobe_video_duration(path: Path) -> float:
    duration = ffprobe_duration(path)
    return duration if duration and duration > 0 else 0.001


def extract_recording_frames(src: Path, dst_dir: Path, fps: int) -> list[Path]:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for existing in dst_dir.glob("frame_*.jpg"):
        existing.unlink()

    vf = f"setsar=1,fps={fps}"
    output_pattern = dst_dir / "frame_%06d.jpg"
    proc = run_command(
        ["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-q:v", "3", str(output_pattern)],
        dst_dir,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to extract browser recording frames from {src}:\n{proc.stderr[-4000:]}")
    frames = sorted(dst_dir.glob("frame_*.jpg"))
    if not frames:
        raise RuntimeError(f"browser recording produced no frames: {src}")
    return frames


class RecordingClip:
    def __init__(self, src: Path, frame_dir: Path, width: int, height: int, fps: int, camera_track: dict[str, Any] | None = None) -> None:
        self.src = src
        self.width = width
        self.height = height
        self.duration = ffprobe_video_duration(src)
        self.frames = extract_recording_frames(src, frame_dir, fps)
        self.camera_track = camera_track if isinstance(camera_track, dict) else {}

    def frame_at(self, progress: float, t: float | None = None) -> Image.Image:
        progress = min(1.0, max(0.0, progress))
        index = min(len(self.frames) - 1, max(0, int(round(progress * (len(self.frames) - 1)))))
        raw = Image.open(self.frames[index]).convert("RGB")
        return apply_recording_camera(raw, self.camera_track, t if t is not None else progress * self.duration, self.width, self.height)


CAMERA_FOCUS_BOXES: dict[str, tuple[float, float, float, float]] = {
    "full_page": (0.0, 0.0, 1.0, 1.0),
    "left_nav": (0.0, 0.0, 0.16, 1.0),
    "feature_menu": (0.0, 0.0, 0.34, 1.0),
    "left_form": (0.0, 0.0, 0.36, 1.0),
    "input_area": (0.0, 0.12, 0.38, 0.68),
    "generate_button": (0.0, 0.66, 0.38, 0.30),
    "result_area": (0.30, 0.08, 0.66, 0.62),
}


def normalized_focus_box(name: str) -> tuple[float, float, float, float]:
    return CAMERA_FOCUS_BOXES.get(name, CAMERA_FOCUS_BOXES["full_page"])


def lerp_box(a: tuple[float, float, float, float], b: tuple[float, float, float, float], value: float) -> tuple[float, float, float, float]:
    eased = smoothstep(value)
    return tuple(a[i] + (b[i] - a[i]) * eased for i in range(4))  # type: ignore[return-value]


def active_camera_segment(camera_track: dict[str, Any], t: float) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    segments = camera_track.get("segments", []) if isinstance(camera_track, dict) else []
    if not isinstance(segments, list) or not segments:
        return None, None
    ordered = [segment for segment in segments if isinstance(segment, dict)]
    ordered.sort(key=lambda segment: float(segment.get("start", 0)))
    active = ordered[0]
    previous = ordered[0]
    for segment in ordered:
        if float(segment.get("start", 0)) <= t:
            previous = active
            active = segment
        else:
            break
    return previous, active


def expand_box_to_aspect(box: tuple[float, float, float, float], aspect: float) -> tuple[float, float, float, float]:
    x, y, w, h = box
    current = w / h if h > 0 else aspect
    if current > aspect:
        new_h = w / aspect
        y -= (new_h - h) / 2
        h = new_h
    else:
        new_w = h * aspect
        x -= (new_w - w) / 2
        w = new_w
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    if x + w > 1:
        x = max(0, 1 - w)
    if y + h > 1:
        y = max(0, 1 - h)
    return (x, y, min(w, 1), min(h, 1))


def apply_recording_camera(image: Image.Image, camera_track: dict[str, Any], t: float, width: int, height: int) -> Image.Image:
    previous, active = active_camera_segment(camera_track, t)
    if not active:
        return fit_width_on_canvas(image, width, height)
    active_focus = str(active.get("focus") or "full_page")
    active_box = normalized_focus_box(active_focus)
    previous_box = normalized_focus_box(str(previous.get("focus") or "full_page")) if previous else active_box
    transition_seconds = 0.45 if str(active.get("transition") or "smooth") == "smooth" else 0.0
    elapsed = max(0.0, t - float(active.get("start", 0)))
    if transition_seconds > 0 and elapsed < transition_seconds:
        box = lerp_box(previous_box, active_box, elapsed / transition_seconds)
    else:
        box = active_box
    if active_focus == "full_page":
        return fit_width_on_canvas(image, width, height)
    box = expand_box_to_aspect(box, width / height)
    x, y, w, h = box
    left = int(round(x * image.width))
    top = int(round(y * image.height))
    right = int(round((x + w) * image.width))
    bottom = int(round((y + h) * image.height))
    cropped = image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
    return ImageOps.fit(cropped, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


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


MOTION_NAMES = {"hold", "push_in", "pull_out"}
MOTION_MAX_AMOUNT = 0.06
TRANSITION_NAMES = {"cut", "crossfade"}
TRANSITION_MAX_DURATION = 0.6


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def event_label(event: dict[str, Any], idx: int | None = None) -> str:
    if event.get("id"):
        return str(event["id"])
    return f"visual_track[{idx}]" if idx is not None else "visual_track event"


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def canonical_layout(event: dict[str, Any], label: str) -> str:
    layout = str(event.get("layout") or "").strip()
    display_mode = str(event.get("display_mode") or "").strip()
    if layout and display_mode and layout != display_mode:
        raise ValueError(f"{label} has conflicting layout/display_mode: {layout!r} != {display_mode!r}")
    return layout or display_mode


def visual_group_key(event: dict[str, Any], label: str | None = None) -> tuple:
    layout = canonical_layout(event, label or event_label(event))
    asset_ids = tuple(str(asset_id) for asset_id in event.get("asset_ids", []))
    return (layout, asset_ids)


def normalize_motion(event: dict[str, Any], label: str) -> dict[str, Any]:
    raw_motion = event.get("motion")
    if raw_motion is None:
        motion: dict[str, Any] = {}
    elif isinstance(raw_motion, dict):
        motion = raw_motion
    else:
        raise ValueError(f"{label}.motion must be an object")
    name = motion.get("name", "hold")
    if name not in MOTION_NAMES:
        raise ValueError(f"{label}.motion.name must be one of {sorted(MOTION_NAMES)}, got: {name!r}")
    amount = motion.get("amount", 0.0)
    if not is_number(amount) or amount < 0 or amount > MOTION_MAX_AMOUNT:
        raise ValueError(f"{label}.motion.amount must be a number in [0, {MOTION_MAX_AMOUNT}], got: {amount!r}")
    anchor = motion.get("anchor", "center")
    if anchor != "center":
        raise ValueError(f"{label}.motion.anchor must be 'center' in this renderer version, got: {anchor!r}")
    amount = float(amount)
    if name == "hold":
        if amount != 0:
            raise ValueError(f"{label}.motion.name=hold requires amount=0, got: {amount!r}")
        amount = 0.0
    return {"name": name, "amount": amount, "anchor": anchor}


def normalize_transition(event: dict[str, Any], label: str) -> dict[str, Any]:
    raw_transition = event.get("transition_in")
    if raw_transition is None:
        transition: dict[str, Any] = {}
    elif isinstance(raw_transition, dict):
        transition = raw_transition
    else:
        raise ValueError(f"{label}.transition_in must be an object")
    name = transition.get("name", "cut")
    if name not in TRANSITION_NAMES:
        raise ValueError(f"{label}.transition_in.name must be one of {sorted(TRANSITION_NAMES)}, got: {name!r}")
    duration = transition.get("duration", 0.0)
    if not is_number(duration) or duration < 0 or duration > TRANSITION_MAX_DURATION:
        raise ValueError(
            f"{label}.transition_in.duration must be a number in [0, {TRANSITION_MAX_DURATION}], got: {duration!r}"
        )
    duration = float(duration)
    if name == "crossfade" and duration <= 0:
        raise ValueError(f"{label}.transition_in.name=crossfade requires duration > 0")
    if name == "cut":
        if duration != 0:
            raise ValueError(f"{label}.transition_in.name=cut requires duration=0, got: {duration!r}")
        duration = 0.0
    return {"name": name, "duration": duration}


def build_visual_groups(track: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive visual_track events that share the exact same visual
    (layout + asset_ids) into one continuous shot. This is the core anti-flicker
    measure: motion runs once across the whole merged span instead of restarting
    per caption change, and no transition is ever drawn between two slices of the
    same visual."""
    events = sorted(
        (
            (idx, event)
            for idx, event in enumerate(track)
            if isinstance(event, dict)
            and isinstance(event.get("start"), (int, float))
            and isinstance(event.get("end"), (int, float))
            and float(event["end"]) > float(event["start"])
        ),
        key=lambda item: item[1]["start"],
    )
    groups: list[dict[str, Any]] = []
    for idx, event in events:
        label = event_label(event, idx)
        key = visual_group_key(event, label)
        motion = normalize_motion(event, label)
        transition_in = normalize_transition(event, label)
        if groups and groups[-1]["key"] == key:
            group = groups[-1]
            if transition_in["name"] != "cut":
                raise ValueError(
                    f"{label} reuses the same visual as the previous event but declares "
                    f"{transition_in['name']} transition; use transition_in.name=cut"
                )
            if motion != group["motion"]:
                raise ValueError(
                    f"{label} reuses the same visual as the previous event but declares different motion"
                )
            group["end"] = max(group["end"], float(event["end"]))
            group["events"].append(event)
            continue
        groups.append(
            {
                "key": key,
                "start": float(event["start"]),
                "end": float(event["end"]),
                "events": [event],
                "asset_ids": [str(asset_id) for asset_id in event.get("asset_ids", [])],
                "layout": key[0],
                "motion": motion,
                "transition_in": transition_in,
            }
        )
    if groups:
        groups[0]["transition_in"] = {"name": "cut", "duration": 0.0}
    return groups


def compose_group_frame(
    case_dir: Path,
    group: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    temp_dir: Path,
    width: int,
    height: int,
    idx: int,
) -> Image.Image:
    asset_ids = group["asset_ids"]
    if not asset_ids:
        raise ValueError(f"visual group missing asset_ids: {group['events'][0].get('id') or idx}")

    images: list[Image.Image] = []
    for asset_id in asset_ids[:4]:
        asset = assets.get(asset_id)
        if not asset:
            continue
        src = resolve_case_path(case_dir, asset.get("source"))
        if src and src.is_file():
            images.append(open_visual_asset(src, temp_dir, idx))
    if not images:
        raise FileNotFoundError(f"no renderable asset for visual group: {group['events'][0].get('id') or idx}")

    layout = group["layout"].lower()
    if len(images) > 1 or layout in {"grid-rebuild", "main-plus-reference"}:
        return grid_on_canvas(images, width, height)
    return fit_width_on_canvas(images[0], width, height)


def is_recording_group(group: dict[str, Any]) -> bool:
    return str(group.get("layout") or "").lower() in RECORDING_LAYOUTS


def apply_motion(base: Image.Image, motion: dict[str, Any], progress: float, width: int, height: int) -> Image.Image:
    """Whole-frame, center-anchored, amount-capped, monotonic scale. This never
    crops into an arbitrary local region of the source image; it always zooms
    the entire composed canvas, which is what keeps the motion from reading as
    an unpredictable local zoom."""
    name = motion.get("name", "hold")
    amount = float(motion.get("amount", 0.0))
    if name == "hold" or amount <= 0:
        return base
    eased = smoothstep(progress)
    if name == "push_in":
        scale = 1.0 + amount * eased
    elif name == "pull_out":
        scale = (1.0 + amount) - amount * eased
    else:
        return base
    scaled_w = max(width, int(round(width * scale)))
    scaled_h = max(height, int(round(height * scale)))
    resized = base.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    left = (scaled_w - width) // 2
    top = (scaled_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


class VisualGroupRenderer:
    """Streams deterministic frames for the merged visual groups: static hold,
    or a small bounded push_in/pull_out, with a crossfade only at boundaries
    where the visual actually changes. No per-frame improvisation."""

    def __init__(
        self,
        case_dir: Path,
        project: dict[str, Any],
        temp_dir: Path,
        width: int,
        height: int,
    ) -> None:
        self.case_dir = case_dir
        self.width = width
        self.height = height
        meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
        self.fps = int(meta.get("fps", 30) or 30)
        self.assets = asset_index(project)
        self.groups = build_visual_groups(project.get("visual_track", []))
        if not self.groups:
            raise ValueError("visual_track produced no renderable groups")
        self.group_starts = [group["start"] for group in self.groups]
        self.temp_dir = temp_dir
        self._base_cache: dict[int, Image.Image] = {}
        self._recording_cache: dict[int, RecordingClip] = {}

    def base_frame(self, group_idx: int) -> Image.Image:
        if group_idx not in self._base_cache:
            self._base_cache[group_idx] = compose_group_frame(
                self.case_dir, self.groups[group_idx], self.assets, self.temp_dir, self.width, self.height, group_idx
            )
        return self._base_cache[group_idx]

    def recording_clip(self, group_idx: int) -> RecordingClip:
        if group_idx not in self._recording_cache:
            group = self.groups[group_idx]
            if not group["asset_ids"]:
                raise ValueError(f"browser recording group missing asset_ids: {group['events'][0].get('id') or group_idx}")
            asset_id = group["asset_ids"][0]
            asset = self.assets.get(asset_id)
            if not asset:
                raise FileNotFoundError(f"browser recording asset missing: {asset_id}")
            src = resolve_case_path(self.case_dir, asset.get("source"))
            if not src or not src.is_file():
                raise FileNotFoundError(f"browser recording source missing: {asset.get('source')}")
            recording_meta = asset.get("recording", {}) if isinstance(asset.get("recording"), dict) else {}
            companions = recording_meta.get("companion_files", {}) if isinstance(recording_meta.get("companion_files"), dict) else {}
            camera_track = load_optional_json(resolve_case_path(self.case_dir, companions.get("recording_camera_track")))
            self._recording_cache[group_idx] = RecordingClip(
                src,
                self.temp_dir / "recording_frames" / f"group_{group_idx:03d}_{src.stem}",
                self.width,
                self.height,
                self.fps,
                camera_track,
            )
        return self._recording_cache[group_idx]

    def frame_for_group(self, group_idx: int, t: float) -> Image.Image:
        group = self.groups[group_idx]
        duration = max(group["end"] - group["start"], 0.001)
        progress = (t - group["start"]) / duration
        if is_recording_group(group):
            return self.recording_clip(group_idx).frame_at(progress, t - group["start"])
        return apply_motion(self.base_frame(group_idx), group["motion"], progress, self.width, self.height)

    def active_group_index(self, t: float) -> int:
        index = bisect_right(self.group_starts, t) - 1
        return min(max(index, 0), len(self.groups) - 1)

    def render_frame(self, t: float) -> Image.Image:
        idx = self.active_group_index(t)
        group = self.groups[idx]
        clamped_t = min(max(t, group["start"]), group["end"] - 1e-4)
        frame = self.frame_for_group(idx, clamped_t)

        transition = group["transition_in"]
        if idx > 0 and transition["name"] == "crossfade" and transition["duration"] > 0:
            elapsed = t - group["start"]
            if 0 <= elapsed < transition["duration"]:
                alpha = smoothstep(elapsed / transition["duration"])
                previous_group = self.groups[idx - 1]
                previous_frame = self.frame_for_group(idx - 1, previous_group["end"] - 1e-4)
                frame = Image.blend(previous_frame, frame, alpha)
        return frame

    def render_report(self) -> list[dict[str, Any]]:
        return [
            {
                "group_index": i,
                "event_ids": [event.get("id") for event in group["events"]],
                "start": round(group["start"], 3),
                "end": round(group["end"], 3),
                "layout": group["layout"],
                "asset_ids": group["asset_ids"],
                "motion": group["motion"],
                "transition_in": group["transition_in"],
            }
            for i, group in enumerate(self.groups)
        ]


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
    ffmpeg_log_path = temp_dir / f"{label}_ffmpeg.log"

    meta = project.get("meta", {})
    width = int(meta.get("width", 1080)) if isinstance(meta, dict) else 1080
    height = int(meta.get("height", 1920)) if isinstance(meta, dict) else 1920
    fps = int(meta.get("fps", 30)) if isinstance(meta, dict) else 30

    # 1. Build ASS subtitles and the deterministic motion/transition timeline.
    subtitle_style_report = build_ass(
        project,
        ass_path,
        width=width,
        height=height,
        font_name=args.subtitle_font_name,
        font_size_override=args.subtitle_font_size,
    )
    renderer = VisualGroupRenderer(case_dir, project, temp_dir, width, height)
    duration = max(
        float(meta.get("target_duration") or 0) if isinstance(meta, dict) else 0,
        renderer.groups[-1]["end"],
    )
    frame_count = max(1, int(round(duration * fps)))

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
    rel_main_output = main_output.relative_to(case_dir).as_posix()

    # Subtitles escaping in FFmpeg can be tricky on Windows.
    # For Windows ffmpeg, colon in paths within filters is extremely problematic,
    # so running from case_dir with pure relative paths is safest.
    filter_complex = f"[0:v]ass='{escape_filter_path(rel_ass)}'[vout]"

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-i", rel_audio_src,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "1:a",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        rel_main_output,
    ]

    print(f"Running FFmpeg (streaming {frame_count} frames): {' '.join(cmd)}", file=sys.stderr)

    # Frames are piped in as raw RGB24 rather than written through the concat
    # demuxer, so every frame comes from one deterministic per-group render
    # function (hold / push_in / pull_out + crossfade) instead of a single
    # static PNG per timeline event. stderr goes to a log file, not a pipe,
    # so a full ffmpeg log buffer can never deadlock against us still writing
    # frames to stdin.
    with open(ffmpeg_log_path, "wb") as log_file:
        proc = subprocess.Popen(
            cmd,
            cwd=str(case_dir),
            stdin=subprocess.PIPE,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            if proc.stdin is None:
                raise RuntimeError("FFmpeg stdin pipe was not created")
            for frame_index in range(frame_count):
                t = frame_index / fps
                frame = renderer.render_frame(t)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        except Exception:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            proc.kill()
            proc.wait()
            raise
        returncode = proc.wait()

    if returncode != 0:
        log_text = ffmpeg_log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg failed:\n{log_text[-4000:]}")

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
        "frame_count": frame_count,
        "fps": fps,
        "rendered_groups": renderer.render_report(),
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
