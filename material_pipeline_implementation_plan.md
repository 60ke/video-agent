# 素材库驱动管线开发实现计划

## 1. 当前已完成

已经新增三份正式 schema：

```text
schemas/material_manifest.schema.json
schemas/material_groups.schema.json
schemas/video_project_v2.schema.json
```

以及说明文档：

```text
schemas/README.md
```

这些 schema 是后续开发的硬契约：

- `material_manifest`：长期素材库资产清单。
- `material_groups`：多图组、功能组、行业组、路径组。
- `video_project_v2`：图片驱动、多轨、可渲染的视频项目。

标准视频链路不再接受浏览器录屏、recording camera track、`crop-focus`、`zoom_to_area` 等不可控局部镜头能力。

## 2. 开发总原则

### 2.1 分层原则

项目拆为两条独立链路：

```text
素材生产链路
视频生产链路
```

素材生产链路可以跑 CDP、读前端源码、调用 GPT image。

视频生产链路不能跑浏览器，不能依赖实时网站状态，只能消费已经入库并通过 QA 的素材。

### 2.2 质量原则

所有图片先按 `display_rule` 排成 1080x1920 base frame，再做整帧动画。

固定渲染顺序：

```text
source image
-> display_rule
-> whole-frame motion
-> overlay/callout motion
-> subtitles
```

禁止：

```text
局部放大
临时裁图修复
录屏虚拟镜头
横图硬裁成竖图局部
把网页结果页截图当最终结果图
```

## 3. 推荐开发阶段

## 阶段一：Schema 校验工具

目标：让所有后续脚本都能校验 manifest、groups、video_project v2。

建议新增：

```text
scripts/validate_material_manifest.py
scripts/validate_material_groups.py
scripts/validate_video_project_v2.py
```

### 3.1 `validate_material_manifest.py`

输入：

```powershell
python scripts\validate_material_manifest.py --manifest materials\sites\kehuanxiongmao\material_manifest.json --json
```

校验：

- JSON schema 合法。
- 每个 `asset_id` 唯一。
- `path` 文件存在。
- 图片可打开。
- `width/height` 与真实图片一致。
- `asset_kind=result_page_evidence` 不允许 `usage=result_showcase`。
- `asset_kind=result_image/case_image` 必须有 claims。
- `visual_state=gpt_9x16/prepared_9x16` 才能进入标准视频。
- `truth.can_claim_real_generation=true` 时必须有 receipt 或可信来源。

输出：

```json
{
  "ok": true,
  "asset_count": 128,
  "warnings": [],
  "errors": []
}
```

### 3.2 `validate_material_groups.py`

输入：

```powershell
python scripts\validate_material_groups.py --manifest materials\sites\kehuanxiongmao\material_manifest.json --groups materials\sites\kehuanxiongmao\material_groups.json --json
```

校验：

- JSON schema 合法。
- 每个 `group_id` 唯一。
- 每个 `asset_id` 在 manifest 中存在。
- gallery / fast cut 组至少 2 张图。
- `site_flow` 组必须推荐 `site_flow_steps`。
- group 的 `usage` 和资产 `usage` 至少有合理交集。
- 同一 group 中 module / industry 不冲突，除非是 `multi_feature_gallery`。

### 3.3 `validate_video_project_v2.py`

输入：

```powershell
python scripts\validate_video_project_v2.py --project cases\<case>\video_project.json --json
```

校验：

- JSON schema 合法。
- `assets` 只能是 image。
- `visual_track` 时间合法，不能负时长。
- `display_rule`、`motion`、`clip_type` 都在白名单。
- `image_sequence/site_flow_steps/result_gallery` 至少 2 张图。
- 所有 `asset_ids` 存在。
- 结果型文案必须绑定 `result_image` 或 `case_image`。
- 多场景、多行业文案必须绑定多图 clip。
- `result_page_evidence` 不能用于 `result_showcase`。
- 禁止出现旧字段：`browser-recording`、`cameraFocus`、`recording_camera_track`、`crop-focus`。

## 阶段二：CDP 素材采集模式

目标：把 `cdp-capture` 从录屏工具改成素材生产工具。

### 2.1 新增无录屏模式

扩展 task JSON：

```json
{
  "captureMode": "material_package",
  "recording": {
    "enabled": false
  }
}
```

当 `recording.enabled=false`：

- 不创建 `Recorder`。
- 不调用 `Page.startScreencast`。
- 不输出 `video.mp4`。
- 不输出 `recording_camera_track.json`。
- 仍然输出 `screenshots/`、`results/`、`metadata.json`、`timeline.json`。
- 仍然保留登录校验、表单校验、结果时间戳闸门。

### 2.2 新增素材任务生成器

建议新增：

```text
cdp-capture/lib/material-task-builder.js
```

CLI：

```powershell
node cdp-capture\bin\cdp-capture.js generate-material-task activity_decoration --output cdp-capture\tasks\material_activity_decoration.json
```

生成任务应覆盖：

```text
首页截图
文生图入口截图
模块菜单截图
功能路由页面截图
功能表单截图
生成按钮 callout 截图
结果页证据截图
真实结果图裁剪/导出
```

它可以复用当前：

```text
references/site_profiles/kehuanxiongmao_text_to_image_modules.json
cdp-capture/lib/nav-task-builder.js
cdp-capture/lib/actions.js
```

但不要再生成录屏相关字段：

```text
cameraFocus
stopRecordingAfter
recording_narration_track
recording_camera_track
```

## 阶段三：素材注册脚本

目标：把 CDP 输出整理进长期素材库，而不是塞进一次性 case。

建议新增：

```text
scripts/register_site_material_package.py
```

输入：

```powershell
python scripts\register_site_material_package.py ^
  --site kehuanxiongmao ^
  --module activity_decoration ^
  --source cdp-capture\output\<task-id> ^
  --library materials\sites\kehuanxiongmao ^
  --json
```

职责：

- 复制 screenshots 到 `materials/sites/.../screenshots/raw`。
- 复制 results 到 `materials/sites/.../results/raw`。
- 按命名规范重命名。
- 写入或更新 `material_manifest.json`。
- 写入基础 `material_groups.json`。
- 记录 `truth.source`、`receipt_id`、`can_claim_real_generation`。
- 标记 `result_page_evidence` 和 `result_image`，不能混淆。

### 3.1 命名策略

效果图：

```text
kx_tti_<module>_<industry>_<scene>_<seq>_result_<aspect>_v1.png
```

网站截图：

```text
kx_tti_<module>_<step>_<seq>_<variant>.png
```

示例：

```text
kx_tti_activity_decoration_route_001_page_empty.png
kx_tti_activity_decoration_form_001_params_clean.png
kx_tti_activity_decoration_result_page_001_evidence.png
kx_tti_activity_decoration_mall_spring_001_result_landscape_v1.png
```

## 阶段四：GPT image 素材关键帧生成

目标：读取素材库 manifest，批量生成可入镜的 9:16 关键帧。

建议新增：

```text
scripts/prepare_material_keyframes.py
```

输入：

```powershell
python scripts\prepare_material_keyframes.py ^
  --manifest materials\sites\kehuanxiongmao\material_manifest.json ^
  --groups materials\sites\kehuanxiongmao\material_groups.json ^
  --asset-kind feature_form_params,result_image ^
  --json
```

职责：

- 读取 manifest 中未处理的 raw/clean/callout 素材。
- 调 GPT image 生成 `gpt_9x16`。
- 输出到素材库对应 `gpt_9x16/` 目录。
- 新增 `gpt_keyframe` 或更新原资产 `visual_state=gpt_9x16`。
- 写回 `source_asset_id`、`display_rule`、`quality.ai_verified`。

提示词原则：

```text
只调整比例、排版、清晰度、留白。
不发明 UI。
不改写中文。
不重新设计结果图。
不新增不存在的产品、按钮、图标、logo。
```

## 阶段五：素材库驱动 Planner

目标：根据视频目标、素材数量、模板，生成 `video_script.json` 和 `video_project_v2.json`。

建议新增：

```text
scripts/build_material_video_project.py
```

输入：

```powershell
python scripts\build_material_video_project.py ^
  --manifest materials\sites\kehuanxiongmao\material_manifest.json ^
  --groups materials\sites\kehuanxiongmao\material_groups.json ^
  --video-type single_feature_seed ^
  --module activity_decoration ^
  --case cases\kx_activity_decoration_seed_001 ^
  --json
```

职责：

- 根据素材组选择模板。
- 生成或接收 reviewed `video_script.json`。
- 结合 Minimax 字幕时间生成 `visual_track`。
- 多图语义使用 `image_sequence` 或 `image_grid`。
- 单图语义使用 `image`。
- 路径证明使用 `site_flow_steps`。
- 结果展示使用 `result_gallery`。

### 5.1 模板选择规则

单功能视频最低门槛：

```text
1 张入口/路径图
1 张功能参数图
3 张结果图
```

多功能合集最低门槛：

```text
至少 3 个功能
每个功能至少 2 张结果图
```

行业垂类最低门槛：

```text
至少 2 个功能模块，或至少 5 张同行业结果图
```

素材不足时：

- 降级文案。
- 降级模板。
- 不允许硬写“多场景”“多行业”“批量出图”。

## 阶段六：FFmpeg 渲染器 V2

目标：让 `render_simple_ffmpeg.py` 支持 schema v2 的多图 clip 和受控动画。

建议可以保留文件名，也可以新增：

```text
scripts/render_material_ffmpeg.py
```

优先支持：

```text
image
image_sequence
image_grid
site_flow_steps
result_gallery
```

### 6.1 Display Rule 实现

`prepared_9x16`：

```text
contain 到 1080x1920
不裁切
```

`portrait_full_width`：

```text
按宽度 1080 等比缩放
高度超过 1920 时仅允许 vertical_pan_for_tall_image
```

`landscape_full_width_center`：

```text
按宽度 1080 等比缩放
上下居中
上下留白用纯色或模糊背景
不裁主体
```

`grid_showcase`：

```text
2-6 张图片排网格
每张图 preserve aspect
不裁主体
```

### 6.2 Motion 实现

只允许：

```text
hold
whole_frame_push_in
whole_frame_pull_out
slide_left
slide_right
slide_up
slide_down
fade
vertical_pan_for_tall_image
grid_to_single
single_to_grid
```

motion 只作用于 base frame。

禁止实现：

```text
crop_focus
zoom_to_area
browser_camera_track
local crop repair
```

## 阶段七：文档与旧链路清理

目标：避免后续 AI 被旧文档带偏。

需要修改：

```text
README.md
SKILL.md
docs/pipeline_v2_refactor.md
rules/kehuanxiongmao-capture.md
rules/vertical-browser-framing.md
references/prompts/script_director.md
```

新文档表达：

- CDP 是素材采集器。
- 标准视频不使用录屏。
- 录屏相关内容迁移到 archived/experimental。
- `register_cdp_recording.py` 不再出现在主流程。
- `video_project_v2` 是标准项目格式。
- 素材必须从 material library 进入视频。

可以归档或删除：

```text
cdp_web_recording_short_video_solution.md
cdp_capture_development_plan.md
cdp-poc/
openbridge_desktop_client_design.md
```

是否删除由当前工作区状态决定，但文档主入口不能再推荐它们。

## 4. 推荐执行顺序

最小可用闭环：

```text
1. validate_material_manifest.py
2. validate_material_groups.py
3. validate_video_project_v2.py
4. register_site_material_package.py
5. prepare_material_keyframes.py
6. build_material_video_project.py
7. render_material_ffmpeg.py
```

如果只想先验证新方向，优先做：

```text
validate_* scripts
register_site_material_package.py
render_material_ffmpeg.py 的 image / image_sequence
```

这样可以最快跑通：

```text
现有图片素材
-> manifest/groups
-> video_project_v2
-> 多图动效视频
```

CDP 批量采集功能可以并行交给其他 AI 做，只要它输出符合 manifest schema 的素材即可。

## 5. 开发验收标准

第一条样板视频应满足：

```text
不使用录屏
至少 1 张路径/入口图
至少 1 张功能参数图
至少 3 张结果图
使用 image_sequence 展示多图
横图左右铺满、上下居中
竖图左右铺满
动画存在但不局部放大
字幕与图片时间区间匹配
contact sheet 能看出信息量明显提升
```

如果做到这些，就说明新架构方向成立。

