# Video Agent V4 Stage 7：V3 删除审计

状态：**Unit 0 已冻结；Unit 6 执行前必须按实际 import graph 复核**

日期：2026-07-20

## 1. 边界

本审计只冻结 V4 生产切换时的删除分类，不在 Unit 0 删除任何 V3 文件，也不修改公共 CLI。正式切换只能由 Stage 7 Unit 5 与 Unit 6 组成同一发布边界。

## 2. A 类：Unit 6 删除

以下模块属于 V3 业务编排或旧 Remotion production composition。在 V4 原生 Narration/Speech、Production Orchestrator、Cover Finalizer 和公共 CLI 全部接线后删除：

| 区域 | 当前入口或依赖 | 删除门禁 |
|---|---|---|
| `video_agent/orchestrator.py` | V3 `Orchestrator` | V4 不再 import `LegacyOrchestrator` |
| `video_agent/planning/` | V3 ActionScene/素材/参数/视觉 Planner | V4 Stage1/4 覆盖生产调用 |
| `video_agent/ai/action_scene_planner.py` | V3 AI Planner | 公共链只调用 V4 Scope/Scene |
| `video_agent/compiler/render_plan.py`、`video_agent/compiler/subtitles.py` | V3 Timeline Compiler | V4 compiler 成为唯一编译器 |
| `video_agent/render/remotion.py` | 固定 `VerticalDemo` | V4 renderer 只调用 `V4Timeline` |
| `remotion/src/VerticalDemo.tsx` 与 `Root.tsx` 中旧 Composition | V3 画面适配器 | `V4Timeline` 生产验收通过 |
| V3 专属 Contract：`action_scene.py`、`narration.py`、`render.py`、`timing.py`、`visual.py` | V3 业务对象 | 共享低层类型先抽离完成 |
| V3 专属 QA、fixtures 和 tests | 只验证旧生产链 | Unit 7 已有等价 V4 验收 |

`video_agent/cover.py::_prepend_one_frame()` 明确属于 A 类。V4 封面只交付独立 `final/cover.png`，不得改变正文视频首帧、总帧数或 Timing Contract。

## 3. B 类：先抽成共享能力，再删除 V3 外壳

以下能力可以复用实现，但不得继续暴露 V3 Contract：

- MiniMax HTTP client、认证加载、一次完整 TTS 请求与 word timestamp parser；
- GPT Image provider client 和通用媒体探测；
- FFmpeg 命令执行、响度探测与安全进程调用；
- 原子 JSON 写入、SHA256、UTC 时间、日志；
- Cover 的图片生成 provider 与参考图拼版低层函数，不包括 V3 `CaseConfig/Narration/VisualPlan` 适配和 `_prepend_one_frame()`；
- Case 导出、清理、素材迁移、审计等管理命令。

抽离后的共享模块不得 import `video_agent.contracts` 中的 V3 业务对象。

## 4. C 类：保留

- `video_agent/contracts/v4/`、`video_agent/compiler/v4/`、`video_agent/render/v4/`；
- Stage 1-5 的 V4 semantic、repository、registry、selection、derivation、motion/SFX 实现；
- `remotion/src/v4/` 与 `V4Timeline`；
- `assets/` 生产素材、Stage3 SQLite/ObjectStore 管理能力；
- 管理型 CLI：素材迁移、审计、inspect、Case 导出与清理；
- Stage0 seeded golden 与 production repository 两套独立验收账本。

## 5. Unit 6 复核命令

删除前后都要保存结果：

```powershell
rg -n "LegacyOrchestrator|from video_agent.orchestrator|VerticalDemo|_prepend_one_frame|contracts import .*TimingLock" video_agent remotion/src tests
rg -n "fallback.*v3|PIPELINE_VERSION|pipeline_version.*v3" video_agent main.py
python -m pytest tests/test_v4_*.py -q
python -m ruff check video_agent tests
```

删除完成条件：

1. 公共 `--script` 与 `--goal` 只进入 V4 Production Orchestrator；
2. 生产 import graph 不包含 V3 Planner、V3 TimingLock、V3 Renderer 或 `VerticalDemo`；
3. V4 失败时没有 V3 fallback；
4. Cover 不再修改正文视频；
5. Unit 5 与 Unit 6 位于同一最终 release tag。
