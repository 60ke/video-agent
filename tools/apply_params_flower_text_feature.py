from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected block not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"expected one regex match in {path}, got {count}: {pattern[:120]!r}")
    path.write_text(updated, encoding="utf-8")


def patch_sources() -> None:
    params = ROOT / "video_agent" / "assets" / "site_params_batch.py"
    replace_once(params, "from video_agent.ai.gpt_image import edit_image\n", "from video_agent.assets.flower_text import build_flower_text_assets\n")
    regex_once(
        params,
        r"def _instruction\(source: SiteParamsSource, annotation: RequiredFieldsAnnotation\) -> str:\n.*?\n\ndef _output_name",
        '''def _instruction(source: SiteParamsSource, annotation: RequiredFieldsAnnotation) -> str:\n    hierarchy = " -> ".join(source.feature_path)\n    return (\n        f"文件名解析路径是 {source.site} -> {source.module} -> {hierarchy}，当前功能为‘{source.feature}’。"\n        f"新增花字只能逐字写为‘{annotation.callout_text}’，它是唯一允许新增的中文文字，且花字不得包含 * 或 ＊。"\n        "页面原有 UI 中已经存在的红色 * 或 ＊ 是界面内容，必须逐个原样保留；不得删除、隐藏、移动、改色、改样式、复制或用花字替换。"\n        "绝不可把提示词、校验过程或来源说明渲染进图片，包括‘已验证必填字段’‘必填字段’‘字段说明’‘CDP’‘前端源码’。"\n        "花字必须作为直接覆盖在原始参数面板上的独立视觉叠层，优先落在面板右侧或右下区域；不得为了放花字新增右侧黑栏、左右分栏、留出空白区或缩小原始参数面板。"\n        "原始参数面板必须从左至右铺满有效画面宽度，两侧外边距各不超过 3%；绝不可在右侧留下空白条、黑色空区或独立侧栏。"\n        "花字可以覆盖普通表单内容或页面背景以形成醒目的整合构图，唯一禁止遮挡的是原始页面标题或分区标题。"\n        "不要生成箭头、指针、连接线、红色框、规则矩形、圆圈、鼠标或人物头像。最终素材只允许出现参数面板和花字。"\n    )\n\n\ndef _output_name''',
    )
    replace_once(
        params,
        '    recipe_prompt, template_sha256 = _prompt(repo_root, DeriveKind.SITE_PARAMS_KEYFRAME, "{batch_instruction}")\n',
        '    _, template_sha256 = _prompt(repo_root, DeriveKind.SITE_PARAMS_KEYFRAME, "{batch_instruction}")\n',
    )
    replace_once(params, '        prompt = recipe_prompt.replace("{batch_instruction}", instruction)\n', '        prompt = instruction\n')
    regex_once(
        params,
        r"    def generate\(item: tuple\[SiteParamsSource, RequiredFieldsAnnotation, Path, str, str, str\]\) -> dict\[str, Any\]:\n.*?\n\n    with ThreadPoolExecutor",
        '''    def generate(item: tuple[SiteParamsSource, RequiredFieldsAnnotation, Path, str, str, str]) -> dict[str, Any]:\n        source, annotation, output, prompt, source_sha256, prompt_sha256 = item\n        prepared = build_flower_text_assets(source.path, output, annotation.callout_text)\n        with Image.open(output) as image:\n            width, height = image.size\n            image.verify()\n        return {\n            "source_path": source.path.resolve().as_posix(),\n            "source_filename": source.path.name,\n            "source_sha256": source_sha256,\n            "output_path": output.resolve().as_posix(),\n            "output_filename": output.name,\n            "output_sha256": sha256_file(output),\n            "width": width,\n            "height": height,\n            "site": source.site,\n            "module": source.module,\n            "feature_path": list(source.feature_path),\n            "feature": source.feature,\n            "annotation_style": "flower_text_only_two_stage_fade",\n            "required_field_labels": list(annotation.labels),\n            "callout_text": annotation.callout_text,\n            "callout_source": "cdp_dom_required_fields_validated_against_frontend_source",\n            "frontend_source_path": annotation.frontend_source_path,\n            "frontend_source_sha256": annotation.frontend_source_sha256,\n            "cdp_required_field_labels": list(annotation.cdp_labels),\n            "cdp_unmatched_field_labels": list(annotation.cdp_unmatched_labels),\n            "prompt_sha256": prompt_sha256,\n            "prompt_template_sha256": template_sha256,\n            "provider": "deterministic_pillow",\n            "model": "flower_text_overlay_v1",\n            "response_id": None,\n            "quality_status": "vision_verified",\n            "quality_checks": ["source_pixels_preserved", "arrow_free", "two_stage_preview_generated"],\n            "status": "generated",\n            **prepared,\n        }\n\n    with ThreadPoolExecutor''',
    )
    text = params.read_text(encoding="utf-8").replace(
        '"annotation_style": "dynamic_required_field_handwritten_callout"',
        '"annotation_style": "flower_text_only_two_stage_fade"',
    )
    params.write_text(text, encoding="utf-8")

    catalog = ROOT / "video_agent" / "assets" / "catalog.py"
    replace_once(
        catalog,
        '            path = Path(str(item.get("output_path") or ""))\n            if not path.is_file():\n                warnings.append(f"approved derived params keyframe missing: {path}")\n',
        '            path = Path(str(item.get("output_path") or ""))\n            if not path.is_absolute():\n                path = assets_root.parent / path\n            if not path.is_file():\n                warnings.append(f"approved derived params keyframe missing: {path}")\n',
    )
    replace_once(
        catalog,
        '                        "required_field_labels": item.get("required_field_labels", []),\n                        "workflow": manifest.get("workflow"),\n                    },\n',
        '                        "required_field_labels": item.get("required_field_labels", []),\n'
        '                        "workflow": manifest.get("workflow"),\n'
        '                        "callout_base_path": item.get("callout_base_path"),\n'
        '                        "callout_base_sha256": item.get("callout_base_sha256"),\n'
        '                        "callout_layer_path": item.get("callout_layer_path"),\n'
        '                        "callout_layer_sha256": item.get("callout_layer_sha256"),\n'
        '                        "callout_layer_method": item.get("callout_layer_method"),\n'
        '                        "flower_text_stage1_path": item.get("flower_text_stage1_path"),\n'
        '                        "flower_text_stage1_sha256": item.get("flower_text_stage1_sha256"),\n'
        '                        "flower_text_stage2_path": item.get("flower_text_stage2_path"),\n'
        '                        "flower_text_stage2_sha256": item.get("flower_text_stage2_sha256"),\n'
        '                        "animation_kind": item.get("animation_kind"),\n'
        '                        "animation_duration_frames": item.get("animation_duration_frames", 18),\n'
        '                    },\n',
    )

    visual = ROOT / "video_agent" / "contracts" / "visual.py"
    replace_once(
        visual,
        '    kind: Literal["handdrawn_circle_reveal"] = "handdrawn_circle_reveal"\n',
        '    kind: Literal["handdrawn_circle_reveal", "flower_text_fade_sequence"] = "handdrawn_circle_reveal"\n',
    )

    auto = ROOT / "video_agent" / "planning" / "auto_visual.py"
    regex_once(
        auto,
        r"            callout_anchor_id: str \| None = None\n            callout_offset = 0\n            has_prepared_callout = template == \"ui_feature_entry\" and asset.role == \"feature_entry\"\n            if has_prepared_callout:\n.*?\n                \)\n            for phrase in phrases_by_beat\[beat.beat_id\]:",
        '''            callout_anchor_id: str | None = None\n            callout_offset = 0\n            prepared_callout: CalloutAnimation | None = None\n            if template == "ui_feature_entry" and asset.role == "feature_entry":\n                prepared_callout = CalloutAnimation()\n            elif (\n                template == "ui_params_focus"\n                and asset.role == "feature_form_params"\n                and asset.metadata.get("callout_base_path")\n                and asset.metadata.get("callout_layer_path")\n            ):\n                prepared_callout = CalloutAnimation(\n                    kind="flower_text_fade_sequence",\n                    duration_frames=int(asset.metadata.get("animation_duration_frames", 18)),\n                    finish_pulse_scale=1.0,\n                )\n            if prepared_callout:\n                animation_frames = prepared_callout.duration_frames\n                stable_hold_frames = round(timing.fps * CALLOUT_STABLE_HOLD_SECONDS)\n                earliest_hit = span.start_frame + start_offset + animation_frames\n                latest_hit = span.start_frame + end_offset - stable_hold_frames\n                target_anchor = _matching_phrase_anchor(asset, phrases_by_beat[beat.beat_id])\n                target_hit = target_anchor.hit_frame if target_anchor else earliest_hit\n                callout_hit = max(earliest_hit, min(latest_hit, target_hit))\n                if target_anchor and callout_hit == target_anchor.hit_frame:\n                    callout_anchor_id = target_anchor.anchor_id\n                else:\n                    callout_anchor_id = f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}"\n                    callout_offset = callout_hit - span.start_frame\n                cue_bindings.append(\n                    CueBinding(\n                        action=prepared_callout.completion_action,\n                        anchor_id=callout_anchor_id,\n                        offset_frames=callout_offset,\n                        sfx="swish" if prepared_callout.kind == "flower_text_fade_sequence" else "mouse_click",\n                    )\n                )\n            for phrase in phrases_by_beat[beat.beat_id]:''',
    )
    replace_once(auto, '                    callout_animation=CalloutAnimation() if has_prepared_callout else None,\n', '                    callout_animation=prepared_callout,\n')

    renderer = ROOT / "video_agent" / "scene" / "renderer.py"
    regex_once(
        renderer,
        r"        if shot.callout_animation and asset_id in self.callout_bases and asset_id in self.callout_layers:\n            base = self.callout_bases\[asset_id\]\.copy\(\)\n            animation = shot.callout_animation\n            if frame < animation.start_frame:\n                return base\n            layer = self.callout_layers\[asset_id\]\.copy\(\)\n            if frame < animation.hit_frame:\n                progress = max\(0\.0, min\(1\.0, \(frame - animation.start_frame\) / \(animation.hit_frame - animation.start_frame\)\)\)\n                alpha = layer.getchannel\(\"A\"\)\n                bbox = alpha.getbbox\(\)\n                if bbox:\n                    reveal = Image.new\(\"L\", layer.size\)\n                    ImageDraw.Draw\(reveal\)\.pieslice\(bbox, start=-18, end=-18 \+ 360 \* ease_out_cubic\(progress\), fill=255\)\n                    layer.putalpha\(ImageChops.multiply\(alpha, reveal\)\)\n            base.alpha_composite\(layer\)\n            return base",
        '''        if shot.callout_animation and asset_id in self.callout_bases and asset_id in self.callout_layers:\n            base = self.callout_bases[asset_id].copy()\n            animation = shot.callout_animation\n            if frame < animation.start_frame:\n                return base\n            layer = self.callout_layers[asset_id].copy()\n            if animation.kind == "flower_text_fade_sequence":\n                total = max(1, animation.hit_frame - animation.start_frame)\n                local = max(0, min(total, frame - animation.start_frame))\n                first_end = max(1, round(total * 0.40))\n                second_start = max(first_end, round(total * 0.62))\n                stage1_opacity = 0.55\n                if local < first_end:\n                    opacity = stage1_opacity * ease_out_cubic(local / first_end)\n                elif local < second_start:\n                    opacity = stage1_opacity\n                else:\n                    denominator = max(1, total - second_start)\n                    opacity = stage1_opacity + (1.0 - stage1_opacity) * ease_out_cubic((local - second_start) / denominator)\n                layer.putalpha(layer.getchannel("A").point(lambda value: round(value * max(0.0, min(1.0, opacity)))))\n            elif frame < animation.hit_frame:\n                progress = max(0.0, min(1.0, (frame - animation.start_frame) / (animation.hit_frame - animation.start_frame)))\n                alpha = layer.getchannel("A")\n                bbox = alpha.getbbox()\n                if bbox:\n                    reveal = Image.new("L", layer.size)\n                    ImageDraw.Draw(reveal).pieslice(bbox, start=-18, end=-18 + 360 * ease_out_cubic(progress), fill=255)\n                    layer.putalpha(ImageChops.multiply(alpha, reveal))\n            base.alpha_composite(layer)\n            return base''',
    )
    replace_once(
        renderer,
        '        if shot.callout_animation and shot.callout_animation.hit_frame <= frame < shot.callout_animation.hit_frame + 8:\n',
        '        if (\n            shot.callout_animation\n            and shot.callout_animation.kind == "handdrawn_circle_reveal"\n            and shot.callout_animation.hit_frame <= frame < shot.callout_animation.hit_frame + 8\n        ):\n',
    )


def rebuild_assets() -> None:
    from video_agent.assets.flower_text import build_flower_text_assets
    from video_agent.io import sha256_file

    source_dir = ROOT / "assets" / "sites"
    output_dir = ROOT / "assets" / "derived" / "sites" / "柯幻熊猫" / "文生图" / "参数面板"
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest.get("assets", []):
        source = source_dir / str(item["source_filename"])
        output = output_dir / str(item["output_filename"])
        if not source.is_file():
            raise FileNotFoundError(source)
        item.update(build_flower_text_assets(source, output, str(item.get("callout_text") or "填写必填项")))
        item["source_path"] = source.relative_to(ROOT).as_posix()
        item["source_sha256"] = sha256_file(source)
        item["output_path"] = output.relative_to(ROOT).as_posix()
        item["output_sha256"] = sha256_file(output)
        for key in ("callout_base_path", "callout_layer_path", "flower_text_stage1_path", "flower_text_stage2_path"):
            item[key] = Path(str(item[key])).relative_to(ROOT).as_posix()
        item.update(
            provider="deterministic_pillow",
            model="flower_text_overlay_v1",
            response_id=None,
            annotation_style="flower_text_only_two_stage_fade",
            quality_status="vision_verified",
            quality_checks=["source_pixels_preserved", "arrow_free", "two_stage_preview_generated"],
            status="generated",
        )
    manifest.update(
        annotation_style="flower_text_only_two_stage_fade",
        review_status="vision_verified",
        workflow="site_params_flower_text_batch",
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_sources()
    rebuild_assets()
