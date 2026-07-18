from __future__ import annotations


def target_size_for_orientation(orientation: str | None, configured: str = "1024x1792") -> str:
    if orientation == "landscape":
        if "x" in configured:
            width, height = configured.lower().split("x", 1)
            if width.isdigit() and height.isdigit():
                return f"{max(int(width), int(height))}x{min(int(width), int(height))}"
        return "1792x1024"
    if orientation == "square":
        return "1024x1024"
    if "x" in configured:
        width, height = configured.lower().split("x", 1)
        if width.isdigit() and height.isdigit():
            return f"{min(int(width), int(height))}x{max(int(width), int(height))}"
    return configured
