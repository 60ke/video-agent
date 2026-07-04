from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any


IMAGE_TYPES = {"image"}
VIDEO_TYPES = {"video"}


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


def copy_media(src: Path, media_dir: Path, prefix: str) -> str:
    if not src.is_file():
        raise FileNotFoundError(f"media not found: {src}")
    dst_dir = media_dir / prefix
    dst_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{prefix}_{len(list(dst_dir.iterdir())) + 1:03d}{src.suffix.lower()}"
    dst = dst_dir / safe_name
    shutil.copy2(src, dst)
    return str(dst.relative_to(media_dir.parent)).replace("\\", "/")


def focus_class(event: dict[str, Any]) -> str:
    framing = event.get("framing", {}) if isinstance(event.get("framing"), dict) else {}
    focus = str(framing.get("focus_region") or "").lower()
    if any(token in focus for token in ("left", "左", "upload", "form", "表单")):
        return "focus-left"
    if any(token in focus for token in ("right", "右", "result", "gallery", "效果")):
        return "focus-right"
    if any(token in focus for token in ("top", "顶部", "header", "nav")):
        return "focus-top"
    if any(token in focus for token in ("bottom", "底部", "button", "生成")):
        return "focus-bottom"
    return "focus-center"


def media_element(media_id: str, media_src: str, asset: dict[str, Any], extra_class: str = "") -> str:
    alt = html.escape(str(asset.get("description") or asset.get("filename") or asset.get("id") or "visual"))
    classes = "visual-media"
    if extra_class:
        classes += f" {html.escape(extra_class)}"
    if asset.get("type") in VIDEO_TYPES:
        return (
            f'<video id="{media_id}" class="{classes}" src="{media_src}" muted playsinline '
            f'preload="auto"></video>'
        )
    return f'<img id="{media_id}" class="{classes}" src="{media_src}" alt="{alt}" />'


def scene_inner(layout: str, media_items: list[dict[str, str]]) -> str:
    if not media_items:
        return ""
    first = media_items[0]
    if layout == "multi-section":
        return f'''
        <div class="section-stack">
          <div class="section-crop section-top">{first["media"]}</div>
          <div class="section-crop section-mid">{first["media_mid"]}</div>
          <div class="section-crop section-bottom">{first["media_bottom"]}</div>
        </div>'''
    if layout == "grid-rebuild":
        cells = "\n".join(f'<div class="grid-cell">{item["media"]}</div>' for item in media_items[:4])
        return f'''
        <div class="media-grid">
          {cells}
        </div>'''
    if layout in {"main-plus-reference", "dual-preview"} and len(media_items) > 1:
        refs = "\n".join(f'<div class="reference-cell">{item["media"]}</div>' for item in media_items[1:3])
        return f'''
        <div class="main-reference-layout">
          <div class="main-cell">{first["media"]}</div>
          <div class="reference-column">{refs}</div>
        </div>'''
    return f'''
        <div class="media-frame">
          {first["media"]}
        </div>'''


def project_duration(project: dict[str, Any]) -> float:
    ends: list[float] = []
    for event in project.get("visual_track", []):
        if isinstance(event, dict) and isinstance(event.get("end"), (int, float)):
            ends.append(float(event["end"]))
    subtitle_track = project.get("subtitle_track", {})
    for event in subtitle_track.get("segments", []) if isinstance(subtitle_track, dict) else []:
        if isinstance(event, dict) and isinstance(event.get("end"), (int, float)):
            ends.append(float(event["end"]))
    voice_track = project.get("voice_track", {})
    if isinstance(voice_track, dict) and isinstance(voice_track.get("duration"), (int, float)):
        ends.append(float(voice_track["duration"]))
    if not ends:
        raise ValueError("cannot determine main video duration from project")
    return round(max(ends), 3)


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = project.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("project.assets must be a list")
    result: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if isinstance(asset, dict) and asset.get("id"):
            result[str(asset["id"])] = asset
    return result


def render_visual_clips(
    case_dir: Path,
    project: dict[str, Any],
    media_dir: Path,
) -> tuple[str, list[str]]:
    assets = asset_index(project)
    clips: list[str] = []
    timeline_lines: list[str] = []

    for idx, event in enumerate(project.get("visual_track", []), start=1):
        if not isinstance(event, dict):
            continue
        start = float(event.get("start", 0))
        end = float(event.get("end", start + 1))
        duration = max(end - start, 0.1)
        asset_ids = event.get("asset_ids", [])
        if not asset_ids:
            continue
        clip_id = f"visual-{idx:03d}"
        layout = html.escape(str(event.get("layout") or "full-preview"))
        media_items: list[dict[str, str]] = []
        for media_idx, asset_id in enumerate(asset_ids[:4], start=1):
            asset = assets.get(str(asset_id))
            if not asset:
                raise ValueError(f"visual event references missing asset: {asset_id}")
            src = resolve_case_path(case_dir, asset.get("source"))
            if not src:
                raise ValueError(f"asset missing source: {asset.get('id')}")
            media_src = copy_media(src, media_dir, "asset")
            media_id = f"{clip_id}-media-{media_idx}"
            media_items.append(
                {
                    "media": media_element(media_id, media_src, asset),
                    "media_mid": media_element(f"{media_id}-mid", media_src, asset, "pos-mid"),
                    "media_bottom": media_element(f"{media_id}-bottom", media_src, asset, "pos-bottom"),
                }
            )
        focus = focus_class(event)
        inner = scene_inner(str(event.get("layout") or "full-preview"), media_items)
        clips.append(
            f'''
      <section id="{clip_id}" class="clip scene {layout} {focus}" data-start="{start:.3f}" data-duration="{duration:.3f}" data-track-index="1">
        <div class="scene-bg"></div>
{inner}
      </section>'''
        )
        fade_out_at = max(end - 0.16, start + 0.04)
        timeline_lines.append(
            f'tl.fromTo("#{clip_id}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.18, ease: "power1.out" }}, {start:.3f});'
        )
        timeline_lines.append(
            f'tl.to("#{clip_id}", {{ opacity: 0, duration: 0.16, ease: "power1.in" }}, {fade_out_at:.3f});'
        )

    return "\n".join(clips), timeline_lines


def render_subtitle_clips(project: dict[str, Any]) -> tuple[str, list[str]]:
    track = project.get("subtitle_track", {})
    segments = track.get("segments", []) if isinstance(track, dict) else []
    clips: list[str] = []
    timeline_lines: list[str] = []
    for idx, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start + 1))
        duration = max(end - start, 0.1)
        text = html.escape(str(segment.get("text") or ""))
        clip_id = f"subtitle-{idx:03d}"
        clips.append(
            f'''
      <div id="{clip_id}" class="clip subtitle-clip" data-start="{start:.3f}" data-duration="{duration:.3f}" data-track-index="5">
        <div class="subtitle-text">{text}</div>
      </div>'''
        )
        timeline_lines.append(
            f'tl.fromTo("#{clip_id} .subtitle-text", {{ y: 18, opacity: 0 }}, {{ y: 0, opacity: 1, duration: 0.12, ease: "power1.out" }}, {start:.3f});'
        )
    return "\n".join(clips), timeline_lines


def copy_voice_audio(case_dir: Path, project: dict[str, Any], media_dir: Path) -> str | None:
    voice = project.get("voice_track", {})
    audio_path = voice.get("audio_path") if isinstance(voice, dict) else None
    src = resolve_case_path(case_dir, audio_path)
    if src and src.is_file():
        return copy_media(src, media_dir, "audio")
    fallback = case_dir / "audio" / "voice.wav"
    if fallback.is_file():
        return copy_media(fallback, media_dir, "audio")
    return None


def build_html(project: dict[str, Any], visual_clips: str, subtitle_clips: str, timeline_lines: list[str], audio_src: str | None) -> str:
    meta = project.get("meta", {})
    width = int(meta.get("width", 1080)) if isinstance(meta, dict) else 1080
    height = int(meta.get("height", 1920)) if isinstance(meta, dict) else 1920
    duration = project_duration(project)
    title = html.escape(str(meta.get("title", "Video Agent Composition")) if isinstance(meta, dict) else "Video Agent Composition")
    audio = f'<audio id="voice-audio" src="{audio_src}" data-start="0" data-duration="{duration:.3f}"></audio>' if audio_src else ""
    timeline = "\n      ".join(timeline_lines)

    return f'''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        background: #070a0f;
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
        color: #fff;
      }}
      #root {{
        position: relative;
        width: {width}px;
        height: {height}px;
        overflow: hidden;
        background:
          linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px),
          radial-gradient(circle at 50% 18%, rgba(0, 174, 255, .16), transparent 44%),
          #070a0f;
        background-size: 72px 72px, 72px 72px, 100% 100%, 100% 100%;
      }}
      .clip {{
        position: absolute;
        inset: 0;
        opacity: 0;
      }}
      .scene-bg {{
        position: absolute;
        inset: 0;
        background: radial-gradient(circle at 50% 45%, rgba(255,255,255,.08), transparent 42%);
      }}
      .media-frame {{
        position: absolute;
        left: 56px;
        top: 132px;
        width: calc(100% - 112px);
        height: 1380px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,.16);
        box-shadow: 0 34px 90px rgba(0,0,0,.46);
        background: rgba(12,16,22,.72);
      }}
      .visual-media {{
        width: 100%;
        height: 100%;
        object-fit: contain;
        object-position: center;
        display: block;
      }}
      .portrait-showcase .media-frame {{
        left: 28px;
        top: 56px;
        width: calc(100% - 56px);
        height: 1620px;
      }}
      .portrait-showcase .visual-media {{
        object-fit: cover;
        object-position: center;
      }}
      .full-preview .media-frame {{
        left: 44px;
        top: 92px;
        width: calc(100% - 88px);
        height: 1520px;
      }}
      .crop-focus .media-frame,
      .ui_operation_focus .media-frame {{
        left: 34px;
        top: 150px;
        width: calc(100% - 68px);
        height: 1320px;
      }}
      .crop-focus .visual-media,
      .ui_operation_focus .visual-media,
      .browser-recording .visual-media {{
        object-fit: cover;
        object-position: center top;
      }}
      .focus-left .visual-media {{ object-position: left center; }}
      .focus-right .visual-media {{ object-position: right center; }}
      .focus-top .visual-media {{ object-position: center top; }}
      .focus-bottom .visual-media {{ object-position: center bottom; }}
      .section-stack {{
        position: absolute;
        left: 48px;
        top: 96px;
        width: calc(100% - 96px);
        height: 1460px;
        display: grid;
        grid-template-rows: repeat(3, 1fr);
        gap: 22px;
      }}
      .section-crop {{
        overflow: hidden;
        border: 1px solid rgba(255,255,255,.16);
        background: rgba(10,14,20,.74);
        box-shadow: 0 22px 56px rgba(0,0,0,.34);
      }}
      .section-crop .visual-media {{
        object-fit: cover;
        object-position: center top;
      }}
      .section-mid .visual-media,
      .section-mid .pos-mid {{
        object-position: center center;
      }}
      .section-bottom .visual-media,
      .section-bottom .pos-bottom {{
        object-position: center bottom;
      }}
      .media-grid {{
        position: absolute;
        left: 48px;
        top: 132px;
        width: calc(100% - 96px);
        height: 1320px;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 24px;
      }}
      .grid-cell,
      .main-cell,
      .reference-cell {{
        overflow: hidden;
        border: 1px solid rgba(255,255,255,.15);
        background: rgba(9,13,19,.78);
        box-shadow: 0 22px 58px rgba(0,0,0,.34);
      }}
      .grid-cell .visual-media {{
        object-fit: cover;
        object-position: center;
      }}
      .main-reference-layout {{
        position: absolute;
        left: 48px;
        top: 118px;
        width: calc(100% - 96px);
        height: 1360px;
        display: grid;
        grid-template-columns: 1.3fr .85fr;
        gap: 24px;
      }}
      .main-cell .visual-media,
      .reference-cell .visual-media {{
        object-fit: cover;
        object-position: center;
      }}
      .reference-column {{
        display: grid;
        grid-template-rows: repeat(2, minmax(0, 1fr));
        gap: 24px;
      }}
      .subtitle-clip {{
        pointer-events: none;
        display: grid;
        align-items: end;
        padding: 0 72px 168px;
      }}
      .subtitle-text {{
        margin: 0 auto;
        max-width: 936px;
        padding: 18px 28px;
        background: rgba(0,0,0,.68);
        border: 1px solid rgba(255,255,255,.16);
        font-size: 36px;
        line-height: 1.35;
        text-align: center;
        text-wrap: balance;
        box-shadow: 0 14px 34px rgba(0,0,0,.34);
      }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-width="{width}" data-height="{height}" data-duration="{duration:.3f}">
      {audio}
{visual_clips}
{subtitle_clips}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      {timeline}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
'''


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path)

    hyperframes_dir = case_dir / "hyperframes"
    media_dir = hyperframes_dir / "media"
    if args.clean and hyperframes_dir.exists():
        shutil.rmtree(hyperframes_dir)
    media_dir.mkdir(parents=True, exist_ok=True)

    visual_clips, visual_timeline = render_visual_clips(case_dir, project, media_dir)
    subtitle_clips, subtitle_timeline = render_subtitle_clips(project)
    audio_src = copy_voice_audio(case_dir, project, media_dir)
    html_text = build_html(project, visual_clips, subtitle_clips, visual_timeline + subtitle_timeline, audio_src)

    index_path = hyperframes_dir / "index.html"
    index_path.write_text(html_text, encoding="utf-8")

    script_text = "\n".join(
        str(seg.get("text", ""))
        for seg in project.get("script_segments", [])
        if isinstance(seg, dict)
    )
    (hyperframes_dir / "SCRIPT.md").write_text(script_text + "\n", encoding="utf-8")
    (hyperframes_dir / "design.md").write_text(
        "# Design\n\nGenerated from video_project.json. Keep timing bound to the project tracks.\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "project": str(project_path),
            "composition_dir": str(hyperframes_dir),
            "index": str(index_path),
            "duration": project_duration(project),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a minimal HyperFrames composition from video_project.json.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--clean", action="store_true")
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
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"HyperFrames composition: {output['data']['index']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
