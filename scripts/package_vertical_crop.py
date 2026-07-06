"""Crop wide browser screenshots into readable 9:16 packaging frames."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps


def crop_region(src: Path, box: tuple[int, int, int, int]) -> Image.Image:
    with Image.open(src) as img:
        return img.convert("RGB").crop(box)


def fit_portrait(image: Image.Image, width: int = 1080, height: int = 1920, *, pad: tuple[int, int, int] = (8, 10, 12), top: int = 90, bottom: int = 250) -> Image.Image:
    canvas = Image.new("RGB", (width, height), pad)
    safe_h = height - top - bottom
    fitted = ImageOps.contain(image, (width - 40, safe_h), method=Image.Resampling.LANCZOS)
    x = (width - fitted.width) // 2
    y = top + (safe_h - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    case_dir = Path(args.case).resolve()
    raw = case_dir / "assets" / "browser" / "raw"
    out = case_dir / "assets" / "browser" / "annotated"
    out.mkdir(parents=True, exist_ok=True)

    # boxes tuned for 1920x855 kehuanxiongmao VI page layout
    jobs = [
        {
            "src": raw / "kx_vi_result_page_004_clean.png",
            "dst": out / "kx_vi_result_010_packaging.png",
            "box": (640, 120, 1905, 835),
            "role": "result_packaging",
        },
        {
            "src": raw / "kx_vi_form_filled_002_clean.png",
            "dst": out / "kx_vi_form_filled_006_packaging.png",
            "box": (150, 60, 700, 820),
            "role": "form_packaging",
        },
        {
            "src": raw / "kx_vi_menu_select_005_clean.png",
            "dst": out / "kx_vi_menu_007_packaging.png",
            "box": (0, 0, 760, 855),
            "role": "navigation_packaging",
        },
        {
            "src": raw / "kx_vi_result_page_004_clean.png",
            "dst": out / "kx_vi_result_full_011_packaging.png",
            "box": (560, 50, 1915, 850),
            "role": "result_full_packaging",
        },
    ]

    written: list[dict[str, str]] = []
    for job in jobs:
        src = job["src"]
        if not src.is_file():
            raise FileNotFoundError(src)
        cropped = crop_region(src, job["box"])
        frame = fit_portrait(cropped)
        job["dst"].parent.mkdir(parents=True, exist_ok=True)
        frame.save(job["dst"])
        written.append({"source": str(src.name), "output": str(job["dst"].relative_to(case_dir)).replace("\\", "/"), "role": job["role"]})

    payload = {"ok": True, "written": written}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in written:
            print(item["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
