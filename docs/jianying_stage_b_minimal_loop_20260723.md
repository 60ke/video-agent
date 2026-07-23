# 剪映 Stage B 最小闭环验证

状态：草稿生成通过，人工导出待验证  
日期：2026-07-23

## 1. 验证输入

- Case：`probe_anchor_wenan_test5_20260722`
- Run：`20260722_164607_3adafc`
- 时间线：`render/compiled_timeline.resolved.json`
- 画布：`1080x1920 / 30fps`
- 总时长：`739` 帧，约 `24.63s`

## 2. 已生成草稿

关键帧映射版：

```text
C:/Users/CNGG/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/VideoAgent_StageAB_Test5_20260723
```

剪映原生动效版：

```text
C:/Users/CNGG/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/VideoAgent_Test5_JianyingNative_20260723
```

场景语义驱动的剪映原生动效版：

```text
C:/Users/CNGG/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/VideoAgent_Test5_SemanticNative_20260723
```

剪映原生全目录检索版：

```text
C:/Users/CNGG/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/VideoAgent_Test5_CatalogNative_20260723
```

原生动效版蓝图与清单：

```text
cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc/jianying_native/edit_blueprint.json
cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc/jianying_native/jianying_project_manifest.json
```

全目录检索版蓝图与清单：

```text
cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc/jianying_native_catalog/edit_blueprint.json
cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc/jianying_native_catalog/jianying_project_manifest.json
```

## 3. 原生动效版结构

| 内容 | 数量 |
|---|---:|
| 画面片段 | 17 |
| 字幕 Cue | 22 |
| 配音 | 1 |
| SFX | 17 |
| 剪映原生转场 | 16 |
| 剪映原生动画材料组 | 25 |
| Remotion 映射关键帧 | 0 |

原生画面动画包括：

- `翻入`
- `缩小`
- `渐显`
- `左拉镜`

原生片段间转场包括：

- Gallery 组内统一使用 `左移`
- 前后图关系使用 `前后对比 II`
- 普通场景边界使用 `叠化`

语义驱动版本不读取旧 Remotion `effect_id` 决定剪映效果。选择依据为首页、Gallery、
参数页、单结果、参考图到结果图、结果图到平面图等场景语义，以及素材横竖方向。
旧 `effect_id` 只为兼容关键帧版蓝图保留，不参与原生剪映动效决策。

全目录检索版进一步移除了上述固定名称映射。语义层只提交
`website_book_open`、`gallery_page_turn`、`causal_before_after`、
`parameter_reveal` 等意图和候选关键词，Adapter 从本机 Skill 的完整剪映枚举中
检索并读取真实 `effect_id`、VIP 状态和默认时长。同一 Gallery 的选择按组缓存，
保证连续镜头使用一致的转场。

本次草稿的实际解析结果：

- 首页首镜：`翻书`，`effect_id=98557334`
- Gallery：8 个 `翻页`，`effect_id=368701`
- 因果对比：2 个 `前后对比 II`，`effect_id=28895844`
- 回到首页：`翻书转场`，`effect_id=92891048`
- 普通边界：`叠化`
- 单结果：`放大弹动`
- 参数页：`渐显`

每次选择均写入 `jianying_project_manifest.json` 的
`native_effect_selections`，包括目标片段、语义意图、枚举类型、名称、资源 ID、
VIP 状态、默认时长和实际应用时长。

字幕使用短 `渐显` 入场，并保留原词级 Cue 区间。所有配音、字幕、画面片段
和 SFX 的开始位置继续来自同一份 `CompiledVideoTimeline`，Adapter 不重新估时。

## 4. 运行命令

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python scripts/jianying_stage_ab.py `
  --run-dir cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc `
  --project-name VideoAgent_Test5_JianyingNative_20260723 `
  --output-subdir jianying_native `
  --motion-backend jianying_native
```

全目录检索版：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python scripts/jianying_stage_ab.py `
  --run-dir cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc `
  --project-name VideoAgent_Test5_CatalogNative_20260723 `
  --output-subdir jianying_native_catalog `
  --motion-backend jianying_native
```

## 5. 当前边界

- `EditBlueprint -> 剪映草稿` 已闭环。
- 原生动效版可由用户在剪映中人工打开、调整和导出。
- 本机剪映为 `11.1.0.14287`，Skill 的自动导出控制器只支持旧版本，因而本阶段
  不声明自动 MP4 导出成功。
