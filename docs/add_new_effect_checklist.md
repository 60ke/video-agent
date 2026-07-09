# 新增第 8 个特效最小改动清单

本文档说明在当前 programmatic image effects 架构下，新增一个第 8 个特效需要改哪些文件、遵守哪些约束，以及如何验证。当前特效系统已经形成：

```text
registry -> effect plan assignment -> effect auxiliary assets -> simple_ffmpeg render
```

新增特效时优先保持这个闭环，不要绕开 `video_project.json`，也不要改变字幕、配音和视觉时间片段。

## 1. 先判断特效类型

新增特效前先确认它属于哪一类：

### A. source-only 特效

只依赖当前图片本身，例如：

```text
blur_in
paper_slide
glitch_reveal
card_stack_single
spotlight_focus
```

这类只需要修改 `utils/effects/registry.py`，通常不需要改 `prepare_effect_assets.py`。

### B. source + auxiliary asset 特效

依赖 GPT Image 或其他方式生成辅助图，例如：

```text
scan_overlay
blueprint_flash
glow_mask_reveal
```

这类除了修改 registry，还需要接入 `prepare_effect_assets.py`，生成并注册辅助资产。

### C. multi-source 特效

依赖多张源图，例如多图卡片堆叠、案例库滑动。第一版不建议直接混入当前单图 effect registry，除非已经明确 `visual_track[].asset_ids` 的多图语义和展示顺序。

## 2. 修改 `utils/effects/registry.py`

这是必须改的核心文件。

### 2.1 注册特效名

在 `EFFECT_NAMES` 增加新特效名：

```python
EFFECT_NAMES = {
    "drop_bounce",
    "pop_in",
    "zoom_pulse",
    "tile_drop",
    "radial_unfurl",
    "wipe_reveal",
    "scan_overlay",
    "new_effect_name",
}
```

命名建议：

```text
小写 snake_case
描述动作，不描述业务
不要包含 feature/product/case 这类业务词
```

### 2.2 增加默认时长

在 `DEFAULT_EFFECT_DURATION` 增加默认时长：

```python
DEFAULT_EFFECT_DURATION["new_effect_name"] = 0.90
```

默认时长建议：

```text
轻量 reveal / pop 类：0.45s - 0.8s
普通 entrance 类：0.8s - 1.1s
复杂拼装类：1.0s - 1.4s
```

### 2.3 增加最小时长

在 `MIN_EFFECT_DURATION` 增加最小时长：

```python
MIN_EFFECT_DURATION["new_effect_name"] = 0.55
```

注意：`normalize_effect_config()` 会把特效时长裁剪到当前 visual group 的安全预算。如果裁剪后时长为 0 或低于最小时长，特效会被禁用，保持静止图展示。

### 2.4 如需辅助图，声明 aux 依赖

如果新特效需要 GPT Image 辅助图，在 `EFFECTS_REQUIRE_AUX` 里增加：

```python
EFFECTS_REQUIRE_AUX = {"scan_overlay", "new_effect_name"}
```

如果只是 source-only 特效，不要加入这里。

### 2.5 实现具体渲染函数

新增私有函数：

```python
def _new_effect_name(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    # t 范围是 0.0 - 1.0
    # 返回一帧 RGB 图像
    return frame.convert("RGB")
```

实现要求：

```text
输入 base 已经是当前 visual group 的基础帧
不要读写磁盘
不要调用网络
不要改字幕、音频、时间
不要依赖全局 case 状态
t=1.0 附近应回到完整清晰原图
输出尺寸必须与 base 一致
```

### 2.6 在 `render_effect_frame()` 中路由

增加分支：

```python
if name == "new_effect_name":
    return _new_effect_name(base, t, params)
```

如果需要辅助图：

```python
if name == "new_effect_name":
    return _new_effect_name(base, t, params, aux_assets or {})
```

### 2.7 可选：加入 `suggested_effect()` 自动推荐

如果希望编排阶段自动选择该特效，在 `suggested_effect()` 里增加规则：

```python
if data.step_kind == "result" and data.duration >= 1.4:
    return {
        "name": "new_effect_name",
        "duration": min(0.9, data.duration - 0.55),
        "params": {}
    }
```

注意：自动推荐必须保守。宁可不自动分配，也不要在密集 UI / 文字截图上过度使用花哨特效。

## 3. 修改 `scripts/apply_effect_plan.py`

如果新特效会与 `push_in/pull_out` 叠加后显得过乱，需要加入 motion 冻结集合：

```python
MOTION_FREEZE_EFFECTS = {
    "drop_bounce",
    "tile_drop",
    "radial_unfurl",
    "new_effect_name",
}
```

判断标准：

```text
强 entrance / 拼装 / 位移动画：建议 freeze motion
轻 reveal / 高亮 / 扫描：建议保留 motion
```

默认策略是：

```text
--freeze-motion auto
```

只有 `MOTION_FREEZE_EFFECTS` 中的特效会自动把 motion 降级为 `hold`。调用方仍可用：

```bash
--freeze-motion always
--freeze-motion never
```

覆盖默认策略。

## 4. 如果需要 GPT Image 辅助图，修改 `scripts/prepare_effect_assets.py`

source-only 特效跳过本节。

### 4.1 增加 aux asset kind

例如新特效需要 `glow_mask`：

```json
{
  "effect": {
    "name": "new_effect_name",
    "needs_aux_asset": true,
    "aux_asset_kind": "glow_mask"
  }
}
```

### 4.2 增加 prompt builder

新增类似函数：

```python
def glow_mask_prompt(asset: dict[str, Any]) -> str:
    return "..."
```

Prompt 必须遵守：

```text
以源图为唯一事实来源
不新增 UI 状态
不新增品牌文案
不改变原图文字
只生成辅助遮罩/高亮/轮廓/结构图
```

### 4.3 生成并注册辅助 asset

复用现有模式：

```text
assets/effects/<source_asset_id>_<aux_kind>.png
effect_asset_manifest.json
project.assets append/upsert
visual_track[].effect.aux_asset_id 回填
```

注意：辅助图不是新证据图，只是 derived overlay asset。

## 5. 修改文档

至少更新：

```text
docs/effects_pipeline.md
```

需要说明：

```text
特效名
是否 source-only
默认时长和最小时长
是否冻结 motion
适用场景
不适用场景
```

如果该特效会进入 agent 默认能力，也更新：

```text
AGENT.md
agent.md
SKILL.md
```

## 6. 验证清单

### 6.1 语法检查

```bash
python -m py_compile \
  utils/effects/registry.py \
  scripts/apply_effect_plan.py \
  scripts/prepare_effect_assets.py \
  scripts/render_simple_ffmpeg.py \
  scripts/render_with_effects.py
```

### 6.2 时长保护检查

如果新增了新的时长边界规则，更新并运行：

```bash
python scripts/check_effect_timing.py
```

至少验证：

```text
短 visual group 禁用 effect
正常 2s visual group 会裁剪到安全预算
effect 播放结束后回到静止原图
```

### 6.3 dry-run 端到端验证

不调用 GPT Image：

```bash
python scripts/render_with_effects.py \
  --case cases/<case> \
  --project cases/<case>/video_project.json \
  --label new_effect_dry \
  --effect-assets-dry-run \
  --skip-outro \
  --json
```

### 6.4 GPT Image 辅助图验证

如果该特效需要辅助图：

```bash
python scripts/prepare_effect_assets.py \
  --case cases/<case> \
  --project cases/<case>/video_project.effects.json \
  --config config/gpt_image.local.json \
  --json
```

检查：

```text
assets/effects/ 是否生成文件
effect_asset_manifest.json 是否记录 source_asset_id 和 aux_asset_id
video_project.effects.json 是否回填 aux_asset_id
辅助图没有新增 UI、文字、品牌或结果内容
```

## 7. 最小代码模板

以 source-only 特效为例：

```python
# 1. EFFECT_NAMES
"blur_in",

# 2. DEFAULT_EFFECT_DURATION
"blur_in": 0.75,

# 3. MIN_EFFECT_DURATION
"blur_in": 0.45,

# 4. renderer implementation
def _blur_in(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    blur_radius = float(params.get("blur_radius", 18.0)) * (1.0 - ease_out_cubic(t))
    frame = base.filter(ImageFilter.GaussianBlur(blur_radius))
    return frame.convert("RGB")

# 5. render_effect_frame route
if name == "blur_in":
    return _blur_in(base, t, params)

# 6. suggested_effect optional
if data.step_kind == "result" and data.duration >= 1.2:
    return {"name": "blur_in", "duration": min(0.75, data.duration - 0.55), "params": {}}
```

## 8. 合并前检查

新增第 8 个特效前，确认：

```text
[ ] 特效名加入 EFFECT_NAMES
[ ] 默认时长加入 DEFAULT_EFFECT_DURATION
[ ] 最小时长加入 MIN_EFFECT_DURATION
[ ] 实现函数输出尺寸与 base 一致
[ ] render_effect_frame 已路由
[ ] 如需自动编排，suggested_effect 已保守配置
[ ] 如有强运动，MOTION_FREEZE_EFFECTS 已配置
[ ] 如需辅助图，prepare_effect_assets 已生成并回填 aux_asset_id
[ ] docs/effects_pipeline.md 已更新
[ ] py_compile 通过
[ ] check_effect_timing.py 通过
[ ] dry-run 渲染通过
```
