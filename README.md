# Agent Test

这是从 `codex/parameter-frame-sequence` 裁剪出的极简验证分支，只验证一条链路：

```text
文案
  -> MiniMax TTS + word 时间戳
  -> 字幕切分
  -> LLM 场景规划 Agent
  -> CDP 按 recipe 操作网站并录屏
  -> Remotion 根据场景计划剪辑
  -> MP4
```

## 分支边界

仅保留：

- `agent_test/`：TTS、字幕对齐、Agent 场景规划和流水线
- `cdp-capture/`：Chrome CDP 操作录屏
- `remotion/`：网站录屏、结果图、画廊、前后对比和标题卡片
- `examples/`：自包含的模拟图片生成网站
- `tests/`：时间轴和场景规划测试

不保留原项目的素材库、V3/V4 生产 DAG、GPT Image 派生链路、封面、片尾、音效库和历史设计文档。

## 场景类型

- `website_operation`：真实网站操作，必须绑定已有 recipe
- `result_detail`：单张生成结果
- `result_gallery`：多张结果图
- `before_after`：明确的前后对比
- `title_card`：缺少可信画面时兜底

Agent 只能选择场景和素材，不能修改 TTS 产生的文字与时间戳。

## 安装

```bash
python -m pip install -e ".[dev]"
cd cdp-capture && npm install
cd ../remotion && npm install
cd ..
```

复制本地配置：

```bash
cp config/minimax.example.json config/minimax.local.json
```

填写 `api_key` 和 `voice_id`，也可通过 `MINIMAX_API_KEY` 提供密钥。

场景规划支持 OpenAI-compatible Chat Completions：

```bash
export AGENT_TEST_API_BASE=https://your-endpoint/v1
export AGENT_TEST_API_KEY=...
export AGENT_TEST_MODEL=...
```

未配置模型时使用透明的关键词规则，方便先验证 CDP 和 Remotion。

## 运行

```bash
python -m agent_test examples/project.example.json
```

仅生成中间产物，不执行 Remotion：

```bash
python -m agent_test examples/project.example.json --no-render
```

输出目录：

```text
runs/<run_id>/
  timing_lock.json
  subtitles.json
  scene_plan.json
  recordings/
  remotion_props.json
  final/video.mp4
  report.json
```

## 验证

```bash
python -m pytest
python -m compileall -q agent_test
node --check cdp-capture/bin/agent-record.js
cd remotion && npx tsc --noEmit
```
