from __future__ import annotations

from types import SimpleNamespace

from video_agent.semantic.registry_payload import scene_material_availability_payload


def test_scene_material_availability_is_semantic_and_uses_relative_object_keys() -> None:
    active = SimpleNamespace(
        asset_role="other",
        category_id="文生图/编辑小工具",
        filename="柯幻熊猫_AI工具_功能列表截图.png",
        object_key="assets/sites/柯幻熊猫_AI工具_功能列表截图.png",
        description="柯幻熊猫图片编辑小工具总览页面",
        orientation=SimpleNamespace(value="landscape"),
        status=SimpleNamespace(value="active"),
    )
    superseded = SimpleNamespace(
        asset_role="result_image",
        category_id="文生图/文化墙",
        filename="old.png",
        object_key="assets/results/old.png",
        description=None,
        orientation=SimpleNamespace(value="landscape"),
        status=SimpleNamespace(value="superseded"),
    )

    payload = scene_material_availability_payload([superseded, active])

    assert payload["source"] == "v4_active_asset_repository"
    assert payload["role_category_availability"] == [
        {
            "asset_role": "other",
            "category_id": "文生图/编辑小工具",
            "count": 1,
            "orientations": ["landscape"],
            "examples": [
                {
                    "filename": "柯幻熊猫_AI工具_功能列表截图.png",
                    "object_key": "assets/sites/柯幻熊猫_AI工具_功能列表截图.png",
                    "description": "柯幻熊猫图片编辑小工具总览页面",
                }
            ],
        }
    ]
