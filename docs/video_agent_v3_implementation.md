# Video Agent V3 实现说明

> 日期：2026-07-11
> 状态：V3 主链已实现并通过 VI、文化墙 Golden Case

## 1. 唯一运行链

`video_agent.runtime.STAGES` 定义唯一 DAG：

```text
catalog -> materialize -> narration -> speech -> visual -> compile -> render -> qa
```

对外入口只有 `python -m video_agent`。每一阶段的输入输出位于同一 `runs/<run_id>/`，可用 `--resume` 和 `--from-stage` 定位重跑。

## 2. 已实现能力

- Pydantic V3 权威契约和原子 JSON 写入；
- 中文站点/结果素材解析、内容哈希 ID、三级语义路径和 CDP callout 锚点；
- E0-E3 证据分级、父素材 provenance、GPT Image 派生审核闸门；
- Minimax `speech-2.8-hd`、默认速度 1.5、真实 `word` 时间戳；
- 仅允许标点缺失的严格字序对齐，不存在比例 timing fallback；
- 标点标签与实测 pause event、有效语速 QA；
- Beat 边界字幕切分、单行 10 单位限制、关键词强调；
- Claim -> supporting asset -> visible shot 的事实证据闭环；
- 一个 Beat 多 Shot、连续 base 轨和可重叠 overlay 轨，支持真实 crossfade / 左右滑动；
- 视觉/SFX 共用 phrase anchor 或镜头起始 anchor，SFX onset/peak 可提前起播，绝对帧编译；
- 抖音安全区、低对比网格舞台、动态 UI 聚焦、结果图完整展示；
- 参数表单等文字密集 UI 仅允许等比缩放或淡变，禁止透视和滑页形变；
- `perspective_push_in` 仅作短暂入场，18% 镜头时长后回到无透视清晰卡片；
- 语义 SFX profile、单音效增益/裁切/淡入淡出、优先级和时间窗口限流；
- 品牌素材库注册、CTA/等待语义选材，以及透明 GIF/MP4 的确定性逐帧渲染；
- Voice/BGM/SFX 多轨混音、BGM ducking、`-16 LUFS` 输出归一；
- 最终 MP4 分辨率、帧数、时长、音轨、响度、字幕、密度和时间轴 QA；
- 可选多模态 Visual Planner 与 Contact Sheet Vision Critic；
- `--resume` 记录并校验阶段 input/output SHA256，从首个失效阶段继续；

## 3. 派生素材

`MaterializationPlan` 支持确定性 `crop_and_reframe` 和受控 GPT Image 派生。网站截图禁止进入 GPT Image 编辑。语义派生输出为 E2 且默认 `unreviewed`，不能被 Planner 或 Compiler 使用，直到：

```powershell
python -m video_agent asset-review --case <case> --run <run_id> --asset-id <id> --approve --json
```

生成成功不等于视觉验收成功。

## 4. Golden Cases

案例：`golden_cases/vi_v3`。

- 时长：18.3 秒；
- 画面：1080×1920，30fps；
- 时间轴：连续覆盖全部帧；
- 音频：AAC，实测约 -16.60 LUFS / -1.52 dBTP；
- UI 命中：VI 入口、品牌名称、开始生成；
- 字幕：单行、Beat 内切分、关键词共享 timing anchor；
- 最终 `qa_report.json`：全部硬检查通过。

案例：`golden_cases/culture_wall_v3`。

- 时长：19.3 秒；
- 横向结果图左右铺满、上下居中，使用低对比网格承接；
- 入口和参数页来自同一功能素材；
- 社区服务、医疗文化、职工之家和医院关怀结果按标签选材；
- 音频实测约 -16.36 LUFS / -1.48 dBTP；
- 最终 `qa_report.json`：全部硬检查通过。

图文广告三级路径解析已覆盖，并将文件系统安全名 `易拉宝_展架` 还原为功能名 `易拉宝/展架`。正式结果 Golden Case 等待同功能真实结果素材，不使用生成或跨功能图片占位。

文化墙 smoke case 已验证末尾 CTA 自动选择 `brand_ip_video` 的挥手熊猫视频。素材视频原音轨不会进入成片；最终语音、BGM 和 SFX 仍由统一音轨计划混合。

## 5. 本地配置

`config/minimax.local.json`、`config/gpt_image.local.json`、`config/ai.local.json` 均由 `.gitignore` 排除。仓库只提交 `*.example.json`。

### 5.1 语义音效

共享音效位于 `assets/audio/sfx/`，默认 profile 为 `short_video_ui_v1`。自动视觉计划会按镜头语义绑定：

- 功能入口：`ui_click`；
- 参数聚焦：`field_focus`；
- 上传相关短语：`upload`；
- 结果镜头入场：`result_reveal`。

转场类音效绑定镜头起始 anchor，字段操作类音效优先绑定词级 phrase anchor。每个音效可使用 onset 或 peak 同步点，编译器会将文件起播时间前移对应毫秒数；随后按优先级执行最小间隔、重复冷却和三秒窗口限流。

```json
{
  "audio": {
    "sfx_profile": "short_video_ui_v1",
    "sfx_overrides": {},
    "sfx_density": {
      "min_gap_ms": 280,
      "window_ms": 3000,
      "max_events_per_window": 3,
      "repeat_cooldown_ms": 900
    }
  }
}
```

设为 `"sfx_profile": null` 可关闭共享音效；`sfx_overrides` 可按语义 ID 覆盖路径、增益、最长时长、淡入淡出和优先级。

## 6. 验证

```powershell
python -m pytest
python -m compileall -q video_agent
python -m video_agent catalog --assets assets --json
python -m video_agent.audio.generate_builtin --output assets/audio/sfx
```
