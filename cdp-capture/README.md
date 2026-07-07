# CDP Capture

基于 Chrome DevTools Protocol 的网页录屏采集工具。

## 快速开始

### 1. 安装依赖

```powershell
cd cdp-capture
npm install
```

> 如果 npm install 失败，代码会自动回退到 `../openbridge-desktop/node_modules/` 中的 `ws` 和 `ffmpeg-static`。

### 2. 登录采集

用可见 Chrome 打开网站并手动登录，导出 `auth_state.json`：

```powershell
node bin/cdp-capture.js profile login kehuanxiongmao --url https://www.kehuanxiongmao.com
```

- 脚本启动可见 Chrome，使用固定 profile 目录 `profiles/kehuanxiongmao/`
- 用户在 Chrome 中完成登录
- 回到终端按 Enter，脚本导出 cookies + localStorage + sessionStorage

### 3. 执行采集任务

```powershell
node bin/cdp-capture.js run examples/task.example.json
```

或指定环境变量覆盖默认参数：

```powershell
node bin/cdp-capture.js run examples/task.example.json --output ./output/custom
```

### 4. 验证视频

```powershell
node bin/cdp-capture.js verify output/task-2026-07-07_00-00-00-000
```

## 任务 JSON 接口

```json
{
  "profileId": "kehuanxiongmao",
  "url": "https://www.kehuanxiongmao.com",
  "viewport": { "width": 1920, "height": 1080 },
  "recording": {
    "fps": 30,
    "jpegQuality": 78,
    "videoCodec": "libx264",
    "pixelFormat": "yuv420p",
    "crf": "20",
    "preset": "veryfast"
  },
  "chrome": {
    "mode": "headless",
    "port": 9333,
    "extraArgs": []
  },
  "overlay": {
    "enabled": true,
    "cursor": { "color": "#ffffff", "size": 24, "showTrail": false },
    "ripple": { "color": "#ffffff", "duration": 600 },
    "highlight": { "color": "#ffeb3b", "duration": 1000 }
  },
  "actions": [
    { "type": "wait", "duration": 2000 },
    { "type": "scroll", "direction": "down", "amount": 1500, "duration": 5000 },
    { "type": "click_selector", "selector": ".some-button", "moveDuration": 500 },
    { "type": "click_point", "x": 100, "y": 200, "moveDuration": 500 },
    { "type": "type_text", "selector": "#search", "text": "hello", "clear": true },
    {
      "type": "evaluate_js",
      "script": "document.querySelector('.btn').click()",
      "narration": "点击开始生成。",
      "required": true,
      "stopRecordingAfter": true
    },
    { "type": "wait", "duration": 30000 },
    { "type": "screenshot", "name": "final" }
  ],
  "outputDir": "./output"
}
```

### Action 类型

| 类型 | 参数 | 说明 |
|------|------|------|
| `open_url` | `url`, `timeout` | 导航到 URL，等待页面加载 |
| `wait` | `duration` | 等待指定毫秒数 |
| `scroll` | `direction`, `amount`, `duration` | 滚动页面（down/up，像素，持续时间） |
| `click_point` | `x`, `y`, `moveDuration` | 点击指定坐标 |
| `click_selector` | `selector`, `moveDuration` | 点击 CSS 选择器匹配的元素 |
| `type_text` | `selector`, `text`, `clear` | 在元素中输入文本 |
| `evaluate_js` | `script`, `awaitPromise` | 执行任意 JS |
| `screenshot` | `name`, `format` | 截图保存到 screenshots/ |

> 任何 action 可添加 `"required": true`，失败时中止整个任务。
> 任何 action 可添加 `"narration": "..."`，任务结束后会按真实 action 时间导出 `recording_narration_track.json`，用于后续配音/字幕和录屏段对齐。
> 点击生成的 action 可添加 `"stopRecordingAfter": true` 或 `"recordingBoundary": "stop_after"`：该 action 会出现在录屏里，录屏随后停止编码，但后续 actions 会继续在同一个真实浏览器会话中执行，用于等待、截图、导出或裁剪真实结果。

### 录屏边界和真实链路

短视频素材不应录下无意义等待，但自动化任务必须跑完整真实链路：

1. 录屏内执行真实输入、真实选择、真实点击 `开始生成`。
2. 在点击生成 action 上设置 `stopRecordingAfter: true`。
3. 录屏停止后，继续执行等待结果、截图结果页、导出/下载/裁剪结果图等 actions。
4. 最终视频展示的结果图必须来自后续真实结果获取动作，而不是虚构素材或网页静态示例。

### Profile 约定

- `profileId` 为空且 URL 包含 `kehuanxiongmao.com` 时，默认使用固定 profile：`kehuanxiongmao`。
- 柯幻熊猫录制默认要求 `profiles/kehuanxiongmao/auth_state.json` 存在；没有登录态会拒绝执行。
- 登录态通过 `profile login kehuanxiongmao --url https://www.kehuanxiongmao.com` 保存，后续自动化、截图、录屏都复用同一个 profile。

## NDJSON 事件流

CLI 输出 NDJSON 进度事件到 stdout（每行一个 JSON）：

```
{"event":"task.started","timestamp":"...","taskId":"task-...","url":"..."}
{"event":"page.loaded","timestamp":"...","url":"...","loaded":true}
{"event":"action.started","timestamp":"...","actionIndex":0,"actionType":"wait"}
{"event":"action.finished","timestamp":"...","actionIndex":0,"actionType":"wait","durationMs":2000,"status":"success"}
{"event":"recording.started","timestamp":"...","fps":30,"resolution":"1920x1080"}
{"event":"recording.finished","timestamp":"...","rawFrameCount":300,"cfrFrameCount":210}
{"event":"task.finished","timestamp":"...","taskId":"task-...","videoPath":"..."}
```

失败时：
```
{"event":"task.failed","timestamp":"...","error":"...","stack":"..."}
```

## 输出目录结构

```
output/<task-id>/
├─ video.mp4           # 最终视频
├─ task.json           # 任务配置副本
├─ timeline.json       # 每个 action 的时间戳和结果
├─ metadata.json       # 录制元数据（fps、分辨率、帧数等）
├─ recording_narration_track.json # 从 action.narration 派生的旁白时间段
├─ verify.json         # FFmpeg 验证结果
├─ screenshots/        # 截图文件
├─ frames/             # 原始 screencast 帧
├─ cfr_frames/         # CFR 补帧后的帧序列
└─ logs/
   ├─ cdp.log           # CDP 和 Chrome 日志
   ├─ ffmpeg.log        # FFmpeg 编码日志
   └─ events.ndjson     # NDJSON 事件副本
```

## 架构

```
cdp-capture/
├─ bin/
│  └─ cdp-capture.js    # CLI 入口 (profile login / run / verify)
├─ lib/
│  ├── utils.js          # 共享工具函数
│  ├── cdp-client.js     # CDP WebSocket 客户端
│  ├── chrome-launcher.js # Chrome 启动器
│  ├── profile-auth.js   # 登录态管理
│  ├── overlay.js        # Shadow DOM overlay（鼠标/涟漪/高亮）
│  ├── recorder.js       # Screencast 录制 + CFR + FFmpeg
│  ├── actions.js        # 动作执行器
│  ├── timeline.js       # 时间线记录
│  ├── events.js         # NDJSON 事件发射器
│  ├── task-runner.js    # 任务编排器
│  └── verifier.js       # FFmpeg 视频验证
├─ examples/
│  └─ task.example.json
└─ profiles/             # Chrome profile 目录（运行时创建）
```
