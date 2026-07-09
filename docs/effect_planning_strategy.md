# Effect Planning Strategy

本文档说明当前特效选择策略的分层，以及后续如何引入 LLM 动态规划。当前实现仍以程序式固定策略为主，LLM 只通过 `semantic_binding`、`visual_intent`、`material_task`、`effect_hint` 等字段间接影响特效选择。

## 当前结论

当前 PR 的特效选择不是完全由 LLM 动态决定，而是：

```text
LLM 负责：脚本、视觉计划、素材选择、语义字段、可选 hint
程序负责：白名单校验、默认特效分配、时长裁剪、motion 冲突处理、辅助图生成、最终渲染
```

推荐长期架构是：

```text
LLM 提建议
程序做裁决
renderer 只执行合法配置
```

不要让 LLM 直接控制底层动画实现、随意生成特效名或修改时间轴。

## 当前程序式策略

自动分配入口是：

```text
scripts/apply_effect_plan.py
```

核心特效建议函数是：

```text
utils/effects/registry.py::suggested_effect()
```

当前默认映射：

| 语义场景 | 判断依据 | 默认特效 |
|---|---|---|
| 首页 / 功能入口 | `step_kind in {"home", "entry"}` | `drop_bounce` |
| 参数页 / UI 截图 / 宽屏 UI | `step_kind in {"params", "ui"}` 或 `is_wide_ui=True` | `wipe_reveal` |
| 生成结果图 | `step_kind == "result"` 或 `is_generated_result=True` | 短段用 `tile_drop`，长段用 `radial_unfurl` |
| 结构解析 / 高亮说明 | 文案或 intent 包含 `解析`、`结构`、`高亮`、`analysis`、`blueprint`、`scan` | `scan_overlay` |
| 普通单图 | 时长充足但无明确场景 | `pop_in` |
| 太短片段 / 序列图 / 非 image clip | 安全性不足 | 不挂特效 |

## 时间安全策略

特效不能改变 `voice_track`、`subtitle_track`、`visual_track` 的时间边界。

当前规则：

```text
visual group start/end 是硬边界
effect 只在 visual group 开头播放
effect 播完后保持静止原图直到 visual group.end
```

`normalize_effect_config()` 会把特效时长裁剪到安全预算内：

```text
effect_duration <= 原始配置时长
effect_duration <= group_duration - 0.55
effect_duration <= group_duration * 0.55
```

如果裁剪后时长为 0，或者低于该特效最小时长，则禁用 effect。临界值使用 `EFFECT_DURATION_EPSILON` 避免浮点误差导致误禁用。

## Motion 冲突策略

默认策略是：

```bash
--freeze-motion auto
```

在 `auto` 下，只有强出场 / 拼装类特效会冻结已有 `push_in` / `pull_out` motion：

```text
drop_bounce
tile_drop
radial_unfurl
```

轻量特效默认保留已有 motion：

```text
pop_in
zoom_pulse
wipe_reveal
scan_overlay
```

调用方可以显式覆盖：

```bash
--freeze-motion auto     # 默认，只冻结强动效
--freeze-motion always   # 所有效果都冻结 motion
--freeze-motion never    # 所有效果都保留 motion
```

## 为什么当前不让 LLM 完全自由选择

完全放开 LLM 直接控制特效会带来这些风险：

```text
生成不存在的 effect.name
特效时长超过 visual group
破坏字幕/配音节奏
同一张图在相邻字幕段反复触发动效，造成闪烁
对 UI 截图使用过强运动，导致看不清内容
声明需要辅助图但没有生成 aux_asset_id
错误把辅助图当作证据图
```

因此即使未来接入 LLM effect planner，也必须保留程序侧校验。

## 推荐的 LLM 动态规划方案

后续可以新增一个 LLM 规划脚本，例如：

```text
scripts/plan_effects_llm.py
```

输入：

```text
video_script.json
visual_plan.json
video_project.json
image_resources.json / asset_manifest.json
```

输出：

```text
video_project.effects.planned.json
```

LLM 只允许在白名单内选择：

```json
{
  "effect": {
    "name": "scan_overlay",
    "duration": 1.2,
    "params": {
      "band_width": 0.14,
      "overlay_opacity": 0.72
    },
    "needs_aux_asset": true,
    "aux_asset_kind": "highlight_overlay",
    "planner": "llm",
    "reason": "该镜头用于强调网站功能结构和按钮区域"
  }
}
```

程序仍然必须执行：

```text
1. effect.name 必须在 EFFECT_NAMES 中
2. duration 必须经 normalize_effect_config() 裁剪
3. 太短片段禁用 effect
4. 需要辅助图的 effect 必须经过 prepare_effect_assets.py
5. motion 冲突必须经过 --freeze-motion 策略处理
6. 相邻同视觉 group 不允许产生不一致 effect
7. renderer 只执行已经归一化后的 effect
```

## 建议的最终链路

当前链路：

```text
video_project.json
  -> apply_effect_plan.py      # 程序式默认策略
  -> prepare_effect_assets.py  # GPT Image 辅助图
  -> render_simple_ffmpeg.py   # 最终渲染
```

升级后链路：

```text
video_project.json
  -> plan_effects_llm.py       # LLM 在白名单内给出建议，可选
  -> apply_effect_plan.py      # 程序兜底 + 校验 + motion 策略
  -> prepare_effect_assets.py  # GPT Image 辅助图
  -> render_simple_ffmpeg.py   # 最终渲染
```

其中 `apply_effect_plan.py` 应该继续作为安全闸门。LLM 可以提高镜头级选择的智能度，但不应该绕过白名单、时长保护、motion 冲突处理和辅助图生成链路。

## 最小实现计划

如果要在下一版接入 LLM effect planner，可以按这个顺序做：

```text
1. 增加 scripts/plan_effects_llm.py
2. 让 LLM 输出 visual_track[].effect_candidate，而不是直接覆盖 effect
3. apply_effect_plan.py 增加 --planner llm|rule|hybrid
4. hybrid 模式优先读取 effect_candidate，失败则回退 suggested_effect()
5. normalize_effect_config() 继续做最终时长裁剪
6. prepare_effect_assets.py 继续处理 needs_aux_asset
7. render_simple_ffmpeg.py 不感知 planner 来源，只渲染合法 effect
8. report 中记录 planner、reason、fallback_reason
```

推荐默认：

```text
--planner hybrid
```

这样既保留规则兜底，又允许 LLM 根据镜头文案、图片内容和素材语义做更细的特效选择。
