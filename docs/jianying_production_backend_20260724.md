# 剪映生产后端实施说明

状态：已实现首个生产闭环

## 1. 已实现边界

当前代码已将外部 `jianying-editor-skill` 作为可探测、可替换的编辑执行后端接入
Video Agent。剪映不重新理解文案，也不重新计算时长，只消费 Stage6 已冻结的
`compiled_timeline.resolved.json`。

```text
CompiledVideoTimeline
  -> JianyingEditBlueprint
  -> JianyingEditorBackend
  -> Jianying Skill Runtime
  -> 剪映原生草稿
```

已支持：

- 从显式参数、`JY_SKILL_ROOT`、仓库约定目录或桌面目录发现 Skill；
- 校验 Skill 版本、模块和能力指纹；
- 生成 1080x1920、30fps 剪映原生草稿；
- 写入图片视觉轨、MiniMax 口播、SFX 和字幕；
- 按场景语义从 Skill 枚举中选择剪映原生转场和动画；
- 同一 Gallery 组复用同一种原生转场；
- 保存 `EditBlueprint`、能力快照和原生动效选择清单；
- 通过公共生产 CLI 选择 `remotion` 或 `jianying` 后端。

剪映后端输出草稿时，口播、字幕、画面切点和 SFX 仍来自同一份词级 Anchor。
Adapter 不允许用自然语言或经验值重新估时。

## 2. Skill 集成方式

Skill 没有复制进本仓库。`JianyingSkillRuntime` 负责发现和加载指定版本，生产代码
只通过 `JianyingEditorBackend` 使用它。这样 Skill 可以独立升级，同时每次 Run
都会记录其版本和能力指纹。

关键模块：

```text
video_agent/editors/jianying/runtime.py
video_agent/editors/jianying/backend.py
video_agent/editors/jianying/compiler.py
video_agent/editors/jianying/adapter.py
video_agent/editors/jianying/native_catalog.py
video_agent/editors/jianying/contracts.py
```

可选的语义子模型不参与帧级时间、坐标或原生素材 ID 决策。未来若启用，它只能
输出场景级导演意图，最终能力解析仍由 Registry 和确定性程序完成。

## 3. 能力探针

```powershell
python main.py jianying-probe --json `
  --jianying-skill-root "C:\Users\CNGG\Desktop\jianying-editor-skill"
```

探针区分：

- `draft_creation` 等已经实际接线的生产能力；
- `screen_recording_tool_present` 等仅表示脚本存在的工具；
- `auto_export_supported` 表示当前剪映版本是否真的可被控制器导出。

“工具存在”不得被解释为“生产链路已支持”。

## 4. 真实验证

已使用以下冻结时间线创建草稿：

```text
cases/probe_anchor_wenan_test5_20260722/
  runs/20260722_164607_3adafc/
  render/compiled_timeline.resolved.json
```

草稿：

```text
C:/Users/CNGG/AppData/Local/JianyingPro/User Data/Projects/
com.lveditor.draft/VideoAgent_JianyingIntegration_20260724
```

本次草稿包含：

| 项目 | 数量 |
|---|---:|
| 总帧数 | 739 |
| 视觉片段 | 17 |
| 字幕 Cue | 22 |
| 音频片段 | 18 |
| 原生转场 | 16 |
| 原生动画 | 4 |

## 5. 当前不支持

- 普通视频或 CDP 录屏作为时间线视觉片段；
- overlay 多轨、鼠标事件、点击波纹和局部放大事件；
- 将 Skill 自带录屏脚本直接编译为 `CaptureBundle`；
- 剪映 11.1 自动导出 MP4。

外部 Skill 的录屏辅助脚本目前调用了未暴露的 CLI/项目方法，因此只能记录为
工具存在，不能接入生产 DAG。自动导出控制器只兼容较旧剪映版本，也必须保持
fail-loud。

## 6. 下一阶段

下一阶段应保持现有后端边界，新增三个独立端口：

```text
CapturePort: CaptureRecipe -> CaptureBundle
EditorPort: CompiledTimeline -> JianyingDraft
ExportPort: JianyingDraft -> ExportedVideo
```

优先顺序：

1. 扩展 Blueprint 和 Compiler，使其支持视频视觉片段及 source in/out；
2. 将 CDP/录屏事件归一为 `CaptureBundle`，再注册为普通素材；
3. 增加 overlay、点击与鼠标事件轨；
4. 单独适配并验证剪映 11.1 导出控制器。

在这些能力完成前，剪映后端的正式交付物是原生草稿，不是自动导出的成片。
