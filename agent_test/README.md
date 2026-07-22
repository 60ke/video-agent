# Agent Test：极简 Agent 驱动视频剪辑验证

这个目录是从 `codex/parameter-frame-sequence` 分支抽出的最短验证链路。它不替代 V3/V4 主架构，只验证下面五件事是否能够闭环：

```text
文案
  -> MiniMax TTS + word 级时间戳
  -> 字幕 cue（继续使用同一份词级时间轴）
  -> Agent 场景分类
  -> CDP 按 recipe 操作网站并录制 MP4
  -> Remotion 根据场景计划、录屏、结果图和字幕渲染成片
```

## 保留与删除的边界

保留：

- MiniMax `subtitle_type=word`。
- `timing_lock.json` 中的 word token 作为声音、字幕和镜头唯一时间源。
- 先分类场景，再选择素材与动效。
- 网站操作必须引用已存在的 CDP recipe，Agent 不能编造 selector。
- Remotion 负责画面、字幕和人声合成。

本验证链路暂不接入：

- 全量素材 Catalog、关系图和 GPT Image 派生。
- V4 Repository/SQLite/Capability Registry。
- BGM、SFX、封面、片尾和复杂 QA。
- 多轮自动修复与任务队列。

## 场景类型

| 场景 | 用途 | 画面来源 |
|---|---|---|
| `website_operation` | 打开页面、上传、选择、输入、点击生成 | CDP recipe 录屏 |
| `result_detail` | 单张图片生成结果 | 结果图 |
| `result_gallery` | 多张结果图/多个案例 | 结果图列表 |
| `before_after` | 原图与生成/编辑后对比 | 两张有明确关系的图片 |
| `title_card` | 没有可信视觉证据时的兜底 | 纯文字卡片 |

## 安装

```powershell
python -m pip install -e ".[dev]"

Set-Location cdp-capture
npm install
Set-Location ..\remotion
npm install
Set-Location ..
```

还需要系统可执行文件：

- Chrome / Chromium
- FFmpeg / FFprobe
- Node.js 18+

## MiniMax 配置

继续复用主项目的本地配置：

```text
config/minimax.local.json
```

也可以通过环境变量覆盖 API Key：

```powershell
$env:MINIMAX_API_KEY="..."
```

配置必须提供 `voice_id`。调用固定要求：

```json
{
  "subtitle_enable": true,
  "subtitle_type": "word"
}
```

## 可选 Agent 模型

没有模型配置时，场景 Planner 使用可解释的确定性规则，方便快速验证浏览器录屏与 Remotion。

需要使用 OpenAI-compatible 模型时：

```powershell
$env:AGENT_TEST_API_BASE="https://your-endpoint/v1"
$env:AGENT_TEST_API_KEY="..."
$env:AGENT_TEST_MODEL="your-model"
```

模型只负责给每个字幕 cue 分类和绑定已有 recipe/结果图，不能修改口播、字幕时间或编造 recipe。

## 项目文件

最小项目：

```json
{
  "title": "网站功能快速验证",
  "script": "打开网站，上传图片，选择风格，点击生成。看，效果图已经出来了。",
  "recipes": {
    "demo": "agent_test/examples/website.recipe.json"
  },
  "result_assets": [
    "assets/results/example.png"
  ]
}
```

`recipes` 的值既可以是 JSON 文件路径，也可以直接嵌入 recipe 对象。

## 运行

完整生成：

```powershell
python -m agent_test agent_test/examples/project.example.json
```

只生成时间轴、场景计划、CDP 录屏和 Remotion Props，不渲染：

```powershell
python -m agent_test agent_test/examples/project.example.json --no-render
```

输出目录：

```text
agent_test_runs/<run_id>/
  project.json
  timing_lock.json
  subtitles.json
  scene_plan.json
  recordings/<recipe_id>/recording.mp4
  remotion_props.json
  final/video.mp4
  report.json
```

## CDP recipe

支持的最小步骤：

```text
open / goto
wait
wait_for_selector
click
fill
select
scroll
key
evaluate
```

示例：

```json
{
  "profile_id": "kehuanxiongmao",
  "mode": "visible",
  "width": 1440,
  "height": 900,
  "fps": 30,
  "start_url": "https://www.kehuanxiongmao.com",
  "steps": [
    {"type": "wait_for_selector", "selector": "[data-testid='feature-entry']"},
    {"type": "click", "selector": "[data-testid='feature-entry']"},
    {"type": "wait", "ms": 800},
    {"type": "fill", "selector": "textarea", "value": "科技感企业文化墙"},
    {"type": "click", "selector": "[data-testid='generate-button']"},
    {"type": "wait_for_selector", "selector": "[data-testid='result-image']", "timeout_ms": 180000},
    {"type": "wait", "ms": 1200}
  ]
}
```

真实站点 recipe 必须使用稳定 selector。登录态复用 `cdp-capture/profiles/<profile_id>`；不要把密码、Cookie 或 Token 写进 recipe。

## 快速验证顺序

1. 先用一个短文案和一个 recipe 跑 `--no-render`。
2. 检查 `timing_lock.json`、`subtitles.json`、`scene_plan.json`。
3. 单独查看 `recordings/<id>/recording.mp4`，确认操作与等待处理正常。
4. 安装 Remotion 依赖后执行完整渲染。
5. 验证通过后，再逐步接回素材库、音效、封面、片尾和 QA，而不是一次性搬回完整 V3/V4。
