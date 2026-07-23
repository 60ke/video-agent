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

原生动效版蓝图与清单：

```text
cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc/jianying_native/edit_blueprint.json
cases/probe_anchor_wenan_test5_20260722/runs/20260722_164607_3adafc/jianying_native/jianying_project_manifest.json
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

## 5. 当前边界

- `EditBlueprint -> 剪映草稿` 已闭环。
- 原生动效版可由用户在剪映中人工打开、调整和导出。
- 本机剪映为 `11.1.0.14287`，Skill 的自动导出控制器只支持旧版本，因而本阶段
  不声明自动 MP4 导出成功。
