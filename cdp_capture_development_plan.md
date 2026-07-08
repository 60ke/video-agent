# CDP 网页录屏采集开发计划

## Summary

- 基于当前验证成功的 `cdp-poc`，新建产品化子项目 `cdp-capture/`，走外部 Chrome + CDP + `Page.startScreencast` 路线。
- 放弃 Electron MVP 录屏链路；广告屏蔽不再内建，由已安装的 uBlock 扩展/Profile 负责。
- 第一版交互方式定为 **任务 JSON CLI**；录制模式 **headless 优先**；AI 操作允许 **任意 JS**，同时保留结构化动作方便时间线记录。
- 第一版目标：AI 写入任务 JSON -> CLI 启动 Chrome -> 恢复登录态 -> 执行动作/JS -> 注入自定义鼠标和点击动画 -> 录制 1080p/30fps MP4 -> 输出素材包。

## Current CDP PoC Usage And Validation

当前验证代码在：

```text
cdp-poc/
├─ login_profile.js
├─ record_kehuanxiongmao.js
└─ README.md
```

### 1. 登录态采集

用可见 Chrome 打开网站并手动登录：

```powershell
node .\cdp-poc\login_profile.js
```

流程：

- 脚本启动外部 Chrome，并使用固定 profile 目录：

```text
cdp-poc/profiles/kehuanxiongmao/
```

- 用户在可见 Chrome 中完成登录。
- 登录成功后，不要手动关闭 Chrome；回到终端按 Enter。
- 脚本通过 CDP 导出 cookies、localStorage、sessionStorage 到：

```text
cdp-poc/profiles/kehuanxiongmao/auth_state.json
```

### 2. 录制验证

默认录制 `https://www.kehuanxiongmao.com`，打开页面后滚动并输出 MP4：

```powershell
node .\cdp-poc\record_kehuanxiongmao.js
```

指定 1080p / 30fps：

```powershell
$env:CDP_WIDTH = '1920'
$env:CDP_HEIGHT = '1080'
$env:CDP_FPS = '30'
$env:CDP_JPEG_QUALITY = '78'
node .\cdp-poc\record_kehuanxiongmao.js
```

脚本行为：

- 启动外部 Chrome。
- 连接 CDP WebSocket。
- 恢复 `auth_state.json` 中的 cookies 和 storage。
- 打开目标网站并 reload。
- 使用 `Page.startScreencast` 获取 JPEG 帧。
- 按 CFR 30fps 补帧/取帧。
- 调用 FFmpeg 编码为 H.264 MP4。

输出目录格式：

```text
cdp-poc/output/<task-id>/
├─ video.mp4
├─ metadata.json
├─ cdp.log
├─ frames/
└─ cfr_frames/
```

### 3. 已验证结果

已验证 720p / 30fps 输出：

```text
1280x720, 30 fps, 30 tbr
```

已验证 1080p / 30fps 输出：

```text
1920x1080, 30 fps, 30 tbr
```

用于验证的 FFmpeg 命令示例：

```powershell
$ffmpeg = 'C:\Users\CNGG\Documents\video_generate\video-agent\openbridge-desktop\node_modules\ffmpeg-static\ffmpeg.exe'
$video = 'C:\Users\CNGG\Documents\video_generate\video-agent\cdp-poc\output\<task-id>\video.mp4'
& $ffmpeg -hide_banner -i $video 2>&1 | Out-String
```

当前 PoC 说明：

- 已证明外部 Chrome + CDP 可以完成网页打开、登录态恢复、滚动、录屏、FFmpeg 编码。
- 当前 PoC 是单文件脚本验证，不是最终架构。
- 正式开发应将 CDP client、Chrome launcher、profile/auth、overlay、recorder、task runner 拆为模块。

## Key Changes

- 新建 `cdp-capture/` 独立 Node/TypeScript 子项目，包含：
  - `profile login`：可见 Chrome 登录，导出 `auth_state.json`。
  - `run <task.json>`：headless Chrome 执行采集任务。
  - `verify <output-dir>`：调用 FFmpeg 验证分辨率、fps、时长、编码信息。
- 任务 JSON v1 固定接口：
  - `profileId`, `url`, `viewport`, `recording`, `chrome`, `overlay`, `actions`, `outputDir`。
  - `recording` 默认：`1920x1080`, `30fps`, `jpegQuality=78`, `mp4/h264/yuv420p`。
  - `chrome.mode` 默认 `headless`；使用同 profile 目录和已安装 uBlock 扩展环境。
  - `actions` 支持：`open_url`, `wait`, `scroll`, `click_point`, `click_selector`, `type_text`, `evaluate_js`, `screenshot`。
- AI 交互约定：
  - AI 只需生成 `task.json` 并调用 CLI。
  - CLI 输出 NDJSON 进度事件到 stdout：`task.started`, `page.loaded`, `action.started`, `action.finished`, `recording.started`, `recording.finished`, `task.finished`, `task.failed`。
  - 每个 action 都写入 `timeline.json`，包括开始时间、结束时间、参数、结果摘要、截图路径或错误。
- Overlay v1：
  - 通过 CDP `Runtime.evaluate` 注入 Shadow DOM overlay。
  - 支持自定义鼠标光圈、平滑移动、点击涟漪、元素高亮。
  - 样式由 task JSON 的 `overlay` 配置控制：颜色、尺寸、涟漪 duration、是否显示 cursor trail。
  - `click_selector/click_point` 默认先移动鼠标动画，再显示点击动画，再发送真实 CDP input。
- Recorder v1：
  - 使用 `Page.startScreencast` 收 JPEG 帧。
  - 记录原始帧 timestamp，并生成 CFR 30fps 帧序列。
  - FFmpeg 编码输出 `video.mp4`。
  - 输出 `metadata.json`，包含 fps、分辨率、rawFrameCount、cfrFrameCount、durationMs、dropped/duplicated frame 估算、profileId、authStateRestored、chromeMode。

## Output Package

每次任务输出目录固定为：

```text
output/<task-id>/
├─ video.mp4
├─ task.json
├─ timeline.json
├─ metadata.json
├─ verify.json
├─ screenshots/
├─ frames/          # 默认可配置清理
└─ logs/
   ├─ cdp.log
   ├─ ffmpeg.log
   └─ events.ndjson
```

## Test Plan

- Profile 登录测试：
  - `profile login` 后生成 `profiles/<profileId>/auth_state.json`。
  - 再运行同 profile 的任务，metadata 中 `authStateRestored=true`。
- 录制质量测试：
  - 运行 1080p/30fps 滚动任务。
  - `verify` 确认 FFmpeg 输出包含 `1920x1080`、`30 fps`、H.264、时长合理。
- AI 动作测试：
  - 任务 JSON 执行 `scroll`、`click_selector`、`evaluate_js`、`screenshot`。
  - `timeline.json` 中每个 action 有时间戳和结果。
- Overlay 测试：
  - 录制视频中能看到鼠标移动、点击涟漪、元素高亮。
  - overlay 不阻挡页面真实点击。
- 失败场景测试：
  - selector 不存在时 action 失败并写入 timeline。
  - 页面加载超时时输出失败截图和 `task.failed`。
  - Chrome/FFmpeg 不存在时给出明确错误。

## Assumptions

- 第一版不做 HTTP/WS 服务，只做任务 JSON CLI。
- 第一版不实现广告屏蔽模块，依赖当前 Chrome profile 中已安装的 uBlock。
- 第一版允许 `evaluate_js` 执行任意 JS，因为这是当前 AI 快速验证复杂网页的优先能力。
- 第一版 headless 优先；如果后续具体网站登录态或风控不稳定，再新增 `chrome.mode="visible"` 作为任务级选项。
- `cdp-poc/` 保留为验证记录；正式实现放在 `cdp-capture/`。

