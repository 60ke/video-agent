# Agent Test — Website Product Launch Video

这是一个仿照 HyperFrames `product-launch-video` 编排方式实现的极简网站产品视频 Agent。

它不复制 HyperFrames 的 HTML frame worker，而是保留它最关键的工作流思想：

```text
Brief
  -> source inventory
  -> style system
  -> storyboard + locked script
  -> TTS + word timing
  -> time-coded visual plan
  -> CDP website recording
  -> Remotion render
  -> validation
```

## 核心能力

- MiniMax 整段 TTS 和 word 级时间戳；
- 字幕、故事 beat、视觉窗口共享同一时间源；
- Agent 先设计故事，再设计逐 cue 画面；
- 网站操作必须使用可复现的 CDP recipe；
- 支持网站录屏、单结果图、结果画廊、前后对比和文字场景；
- Remotion 根据 `visual_plan.json` 渲染；
- 每个阶段都有落盘产物和 Gate。

完整编排规则见 [`SKILL.md`](SKILL.md)。

## 安装

```bash
python -m pip install -e ".[dev]"
cd cdp-capture && npm install
cd ../remotion && npm install
cd ..
```

准备 MiniMax：

```bash
cp config/minimax.example.json config/minimax.local.json
```

填写 `api_key` 和 `voice_id`，或者通过 `MINIMAX_API_KEY` 提供密钥。

## 创建项目

```bash
python -m agent_test init videos/my-product \
  --title "My Product" \
  --script "输入需求，点击生成，结果马上出现。"
```

生成的项目结构：

```text
videos/my-product/
  BRIEF.md
  SCRIPT.md
  STORYBOARD.md
  STYLE.md
  project.json
  storyboard.json
  capture/inventory.json
  recipes/
  assets/
  work/
  renders/
```

也可以直接复制 `examples/product-demo/`。

## 分阶段运行

```bash
python -m agent_test inventory videos/my-product
python -m agent_test audio videos/my-product
python -m agent_test plan videos/my-product
python -m agent_test build videos/my-product --no-render
python -m agent_test check videos/my-product
python -m agent_test build videos/my-product
```

完整执行：

```bash
python -m agent_test run videos/my-product
```

最终输出：

```text
videos/my-product/renders/video.mp4
```

## 关键产物

```text
capture/inventory.json   # 可用 recipe 和结果素材边界
work/timing_lock.json    # MiniMax word 时间戳
work/subtitles.json      # 可读字幕 cue
work/audio_meta.json     # 音频元数据
work/visual_plan.json    # beat 和视觉窗口的真实时间
work/recordings/         # CDP 操作录屏
work/remotion_props.json # Remotion 输入
work/report.json
renders/video.mp4
```

## 场景类型

- `website_operation`
- `result_detail`
- `result_gallery`
- `before_after`
- `title_card`

## 本地蓝图

- `prompt-submit-result`
- `cursor-ui-demo`
- `result-hero`
- `result-grid`
- `before-after-wipe`
- `kinetic-type`

蓝图只是故事和镜头形状，不负责修改真实素材或捏造功能。

## 验证

```bash
python -m compileall -q agent_test
python -m pytest
node --check cdp-capture/bin/agent-record.js
cd remotion && npx tsc --noEmit
```
