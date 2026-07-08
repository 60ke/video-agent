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
    "cursor": { "color": "#ffffff", "size": 34, "showTrail": true },
    "ripple": { "color": "#ffd54f", "duration": 900 },
    "highlight": { "color": "#38bdf8", "duration": 1200 }
  },
  "actions": [
    { "type": "wait", "duration": 2000 },
    { "type": "scroll", "direction": "down", "amount": 1500, "duration": 5000, "cameraFocus": "full_page" },
    { "type": "click_selector", "selector": ".some-button", "moveDuration": 500, "required": true, "cameraFocus": "left_nav" },
    { "type": "click_point", "x": 100, "y": 200, "moveDuration": 500 },
    { "type": "type_text", "selector": "#search", "text": "hello", "clear": true, "required": true, "cameraFocus": "left_form" },
    {
      "type": "evaluate_js",
      "script": "document.querySelector('.btn').click()",
      "narration": "点击开始生成。",
      "required": true,
      "expectIncludes": "clicked",
      "cameraFocus": "generate_button",
      "emphasis": "generate",
      "stopRecordingAfter": true
    },
    { "type": "wait", "duration": 30000 },
    {
      "type": "capture_element",
      "selector": ".result img, .image-result img, .preview img",
      "name": "real_result",
      "workflowStep": "result_crop",
      "resultAsset": true,
      "required": true,
      "cameraFocus": "result_area"
    }
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
| `evaluate_js` | `script`, `awaitPromise`, `expectIncludes`, `failIfIncludes` | 执行任意 JS，并可校验返回文本 |
| `screenshot` | `name`, `format` | 截图保存到 screenshots/ |
| `capture_element` | `selector`, `name`, `workflowStep`, `resultAsset`, `matchStrategy`, `minWidth`, `minHeight`, `excludeSelectors` | 裁剪指定元素；`resultAsset=true` 时保存到 results/ |
| `wait_for_selector` | `selector`, `timeout`, `pollInterval`, `minWidth`, `minHeight`, `excludeSelectors`, `matchStrategy` | 轮询直到出现可见且达到最小尺寸的匹配元素，超时抛错 |
| `upload_file` | `selector`, `filePath` | 用 `DOM.setFileInputFiles` 上传一张真实本地图片到 file input |
| `mark_result_baseline` | `cardSelector`, `imageSelector`, `stateKey` | 点击生成前记录页面已有历史结果卡片签名 |
| `wait_for_result_after_time` | `cardSelector`, `imageSelector`, `baselineStateKey`, `afterTimeStateKey`, `timeout` | 等待时间戳不早于本次点击生成的新结果卡片出现 |
| `capture_result_after_time` | `cardSelector`, `imageSelector`, `baselineStateKey`, `afterTimeStateKey`, `name`, `loadingSrcIncludes` | 只裁剪时间戳不早于本次点击生成、且图片不是 loading 占位图的新结果 |
| `inspect_required_form` | `stateKey`, `includeOptional`, `values` | 动态扫描当前功能页表单，识别 required 字段、控件类型和值状态 |
| `fill_required_form` | `stateKey`, `values`, `includeOptional` | 按当前页扫描出的字段和给定 values 填写 input/textarea/select，缺 required 值或控件失败会报错 |
| `validate_required_form` | `stateKey`, `generateButtonText`, `requireGenerateButton` | 提交前确认所有 required 字段已填、生成按钮存在且可点击 |

### 结果真实性（重要）

历史上最常见的错误是：结果图不是本次网页真实生成的结果，而是 logo、示例图或空状态占位图被宽泛选择器抓到后当成了结果。为避免这类假阳性：

- **柯幻熊猫文生图先读模块注册表**：执行任务前先看 `../references/site_profiles/kehuanxiongmao_text_to_image_modules.json`，按目标 `module.id` 使用固定 `route`、`label`、`page_title`、`source_type`、`primary_task_type`。CDP 只做现场验证，不负责临场猜模块。
- **导航必须断言模块身份**：进入页面后确认 `location.pathname === module.route`、`.label-active` 等于 `module.page_title`、页面可见 `开始生成`。录屏入口路径需要在 `.hover-submenu-item` 中命中精确菜单文本。
- **不要伪造上传**。`new File([''], ...)` 这种空文件无法生成结果。用 `upload_file` + `filePath`（真实商品图路径）上传，并设 `required: true`。
- **不要假设不同菜单的必填项相同**。进入功能页后先执行 `inspect_required_form`，再用 `fill_required_form` 填当前页真实 required 字段，最后用 `validate_required_form` 确认所有 required 字段已填且 `开始生成` 可点击。任何 required 字段缺值、控件无法填写、按钮不可点，都必须中止。
- **结果 `capture_element` 必须精确锚定生成结果容器**，不能用 `img[src*='img']`、`img[class*='image']` 这类会命中 logo/示例的选择器。
  - `resultAsset: true` 时默认 `matchStrategy: "largest"`，并默认要求最小 `240x240`（可用 `minWidth`/`minHeight` 覆盖），且默认排除 header/nav/logo/avatar/sample 等元素（可用 `excludeSelectors` 追加）。
  - 达不到最小尺寸或无匹配时会直接报错，不会把 logo/缩略图存成结果。
- **抓结果前先用 `wait_for_selector` 等真实结果出现**（同样的精确选择器 + 最小尺寸 + 排除项）。如果生成没真正发生（例如仍是"暂无生成记录"空状态），`wait_for_selector` 会超时，`required` 会中止任务——宁可失败，也不产出假结果。
- **有历史结果列表时，必须用时间戳闸门**：点击生成前先 `mark_result_baseline`，点击后用 `wait_for_result_after_time` / `capture_result_after_time`。结果卡片里的时间必须不早于本次 `开始生成` 点击时间（按页面秒级时间比较），且不能是点击前基线里已经存在的卡片。仅仅页面上"有图"不算成功。
- **创作中不是结果**：如果新卡片图片还是 `https://kehuanxiongmao.com/static/img/generate-loading.a5374121.webp`（或包含 `/static/img/generate-loading`），说明结果尚未完成。`capture_result_after_time` 必须继续轮询，建议柯幻熊猫任务用 `pollInterval: 30000`，直到同一新时间卡片里的图片链接不再是 loading 占位图。
- 注册环节 `scripts/register_cdp_recording.py` 会对 `results/` 里的图做内容校验（最小尺寸、纯色/空白、与已注册素材字节去重），任一不通过就拒绝写入 `verified_result`。可用 `--min-result-width/height` 调整阈值，`--allow-weak-result` 仅在人工确认后使用。

> 任何 action 可添加 `"required": true`，失败时中止整个任务。
> 任何 action 可添加 `"narration": "..."`，任务结束后会按真实 action 时间导出 `recording_narration_track.json`，用于后续配音/字幕和录屏段对齐。
> 任何 action 可添加 `"cameraFocus": "full_page|left_nav|feature_menu|left_form|generate_button|result_area"`，任务结束后会导出 `recording_camera_track.json`，用于最终竖屏视频的虚拟镜头移动。
> 点击生成的 action 可添加 `"stopRecordingAfter": true` 或 `"recordingBoundary": "stop_after"`：该 action 会出现在录屏里，录屏随后停止编码，但后续 actions 会继续在同一个真实浏览器会话中执行，用于等待、截图、导出或裁剪真实结果。
> 点击生成动作可加 `"emphasis": "generate"`，录制时会给按钮更明显的脉冲提示。`type_text` 会默认校验输入值；特殊控件可以显式设置 `"verify": false`。

### 录屏边界和真实链路

短视频素材不应录下无意义等待，但自动化任务必须跑完整真实链路：

1. 录屏内执行真实输入（真实图片走 `upload_file`）、真实选择、真实点击 `开始生成`。
2. 每个必填输入、必选控件和开始生成按钮都必须是 `required: true`；selector 不存在、上传失败、输入失败、按钮不可点都会中止任务，不允许跳过或伪造状态（禁止空文件伪上传）。
3. 在真实点击生成的 action 上设置 `stopRecordingAfter: true`。这只停止录屏，不停止 CDP 自动化任务。
4. 录屏停止后，如果页面会展示历史结果，先用 `wait_for_result_after_time` 等本次点击后新建的结果卡片；结果时间必须 >= 本次点击生成时间。
5. 至少保留一个后置 `capture_result_after_time` 或等价导出动作把真实新结果写入 `results/`。最终视频展示的结果图必须来自同一次 CDP 生成链路，不得使用网页静态示例、旧结果或伪结果。

当任务使用 `stopRecordingAfter` 但后续没有真实结果获取动作时，`cdp-capture run` 会失败；当注册时使用 `scripts/register_cdp_recording.py --ends-after-generation-trigger`，也会要求 `metadata.json` 证明录屏停止后继续执行了结果获取动作，并要求 `results/` 中存在真实结果图片。

### 录制增强与后期镜头

录制时 overlay 会强化光标、点击涟漪、点击前高亮、输入框聚焦描边和开始生成按钮脉冲。这些效果写进录屏素材本身，便于短视频观看时聚焦。

录屏仍按正常横屏浏览器尺寸采集。最终竖屏渲染时，`recording_camera_track.json` 会把真实 action 时间转换成虚拟镜头轨道：先展示 `full_page`，再根据 `cameraFocus` 平滑移动到 `left_nav`、`feature_menu`、`left_form`、`generate_button` 或 `result_area`。如果没有 camera track，渲染器会退回到横屏录屏按 1080px 宽度居中展示。

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
├─ recording_camera_track.json    # 从 action.cameraFocus 派生的虚拟镜头时间段
├─ verify.json         # FFmpeg 验证结果
├─ screenshots/        # 截图文件
├─ results/            # 同一次真实生成链路裁剪/导出的结果图
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
