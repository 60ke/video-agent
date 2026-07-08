# OpenBridge Desktop Client 开发与实现指导文档

> 目标：基于 Electron 快速开发一个“内置浏览器 + 持久化登录态 + AI 操作接口 + 自定义鼠标/点击动画 + 本地录屏/素材导出”的桌面客户端，用于 AI 视频工厂的网站素材采集与自动化演示生成。

---

## 1. 项目背景

当前方案讨论过三类浏览器控制/录屏路线：

1. **Chrome 插件 OpenBridge**  
   适合接管用户真实 Chrome 页面，天然继承用户已登录状态，但受 Chrome Extension 权限、MV3 生命周期、录屏授权、API 限制影响。

2. **Playwright / CDP 自动化浏览器**  
   适合服务端或本地 Agent 启动受控浏览器，做自动化访问、截图、录屏帧采集，但默认不继承用户日常 Chrome 登录态。可以通过独立 profile 保存登录态。

3. **Electron 桌面客户端**  
   适合产品化。它能内置 Chromium 浏览器、持久化登录状态、提供本地 AI 操作 API、内置录屏/截图/FFmpeg，并做更丰富的鼠标动画、点击效果、局部高亮、素材上传等功能。

因此，本项目建议从“Chrome 插件”升级为：

```text
OpenBridge Desktop Client
= Electron 内置浏览器
+ 持久化 Profile
+ AI Action API
+ Overlay 动画层
+ Recorder 录屏引擎
+ Artifact 素材管理
+ 后端/Agent 集成接口
```

---

## 2. 核心目标

### 2.1 产品目标

打造一个桌面客户端，让 AI 可以像用户一样打开网站、登录、点击、输入、滚动、截图、录屏，并将过程素材输出给后续视频生成系统。

典型链路：

```text
用户输入目标网站
→ Electron 内置浏览器打开网站
→ 用户首次手动登录，后续自动保持登录态
→ AI Agent 通过 OpenBridge API 操作网页
→ 客户端展示鼠标轨迹、点击涟漪、元素高亮等效果
→ 客户端录制网页操作过程
→ 输出 video.mp4 / action_timeline.json / screenshots
→ 上传到后端
→ Hyperframes / Remotion / FFmpeg 生成最终短视频
```

### 2.2 工程目标

第一阶段目标不是做完整剪辑软件，而是做一个稳定的“AI 网页操作与视频素材采集器”。

必须支持：

- 内置网页访问。
- 持久化登录状态。
- AI 操作接口。
- 截图。
- 鼠标点击效果与高亮动画。
- 10-30 秒网页操作录屏。
- 输出本地素材文件。
- 后端上传。

暂不作为第一阶段目标：

- 多用户大规模并发。
- 完整视频剪辑时间线。
- 复杂字幕编辑器。
- 直接继承用户 Chrome 默认 Profile。
- 绕过验证码、风控、登录限制。
- 录制 DRM/受保护视频内容。

---

## 3. 技术选型

### 3.1 客户端框架

推荐：

```text
Electron + TypeScript + React/Vue + Vite
```

理由：

- Electron 内置 Chromium，适合嵌入网页。
- 可使用持久化 session 保存登录态。
- 可访问本地文件系统、FFmpeg、WebSocket、本地 HTTP 服务。
- 可通过 WebContents 控制网页、截图、注入脚本、发送输入事件。
- 可结合 desktopCapturer 或 WebContents frame capture 实现录屏。

### 3.2 页面承载

推荐使用：

```text
WebContentsView
```

不要优先使用旧的 `BrowserView` 或 `<webview>`。

原因：

- `WebContentsView` 是 Electron 新版本推荐的嵌入网页方式。
- 能更清晰地隔离“控制面板页面”和“目标网站页面”。
- 目标网站作为不可信远程内容处理，不能直接接触 Node 能力。

### 3.3 登录态保存

使用 Electron session partition：

```ts
session.fromPartition('persist:video-factory-user-001')
```

只要 partition 以 `persist:` 开头，Electron 会持久化 cookies、storage、cache 等状态。

建议设计：

```text
每个用户 / 每个任务账号一个独立 partition
persist:user-001
persist:user-002
persist:demo-account
```

### 3.4 录屏方案

第一阶段优先：

```text
desktopCapturer 捕获 Electron 当前窗口
→ MediaRecorder 得到 WebM
→ FFmpeg 转 MP4
```

优点：

- 开发最快。
- Overlay 动画天然能录进去。
- 适合验证 MVP。

第二阶段增强：

```text
WebContents frame capture / beginFrameSubscription
→ 只采集网页区域
→ Overlay 合成
→ FFmpeg 编码
```

第三阶段扩展：

```text
CDP Page.startScreencast
→ 作为兼容录制驱动
```

---

## 4. 总体架构

```text
OpenBridge Desktop Client

Main Process
├─ AgentApiServer
│  ├─ HTTP API
│  ├─ WebSocket API
│  └─ MCP Adapter，可选
│
├─ ProfileManager
│  ├─ createProfile
│  ├─ switchProfile
│  ├─ clearProfile
│  └─ persist partition 管理
│
├─ BrowserManager
│  ├─ createWebContentsView
│  ├─ loadURL
│  ├─ navigation 管理
│  ├─ permission 管理
│  └─ multi-tab 管理，可选
│
├─ ActionController
│  ├─ click
│  ├─ type
│  ├─ scroll
│  ├─ keypress
│  ├─ wait
│  └─ evaluate，受控
│
├─ PerceptionEngine
│  ├─ screenshot
│  ├─ DOM snapshot
│  ├─ accessibility tree
│  ├─ element bounds
│  └─ visual observe
│
├─ OverlayEngine
│  ├─ cursor halo
│  ├─ click ripple
│  ├─ element highlight
│  ├─ spotlight
│  ├─ zoom focus
│  ├─ keyboard hint
│  └─ step marker
│
├─ RecorderEngine
│  ├─ desktopCapturer recorder
│  ├─ webContents frame recorder，v2
│  ├─ audio capture，可选
│  ├─ FFmpeg encoder
│  └─ CFR 30fps align，可选
│
├─ ArtifactManager
│  ├─ screenshots
│  ├─ raw webm
│  ├─ final mp4
│  ├─ action_timeline.json
│  └─ metadata.json
│
└─ Uploader
   ├─ chunk upload
   ├─ retry
   └─ artifact registry
```

---

## 5. 关键模块设计

## 5.1 ProfileManager

### 职责

管理独立浏览器 Profile，保存用户登录态。

### 功能

```text
create_profile(profile_id)
switch_profile(profile_id)
list_profiles()
clear_profile(profile_id)
export_profile_metadata(profile_id)
```

### 设计原则

- 不直接读取用户 Chrome 默认 Profile。
- 不尝试偷取或迁移用户 cookie。
- 用户在 Electron 内置浏览器中登录一次，后续复用同一 partition。
- 每个 profile 独立存储，避免账号状态串扰。

### 示例

```ts
import { session } from 'electron';

function getProfileSession(profileId: string) {
  return session.fromPartition(`persist:${profileId}`);
}
```

---

## 5.2 BrowserManager

### 职责

创建和管理目标网站 WebContentsView。

### 功能

```text
open_url(url)
reload()
go_back()
go_forward()
set_bounds(x, y, width, height)
get_current_url()
get_title()
```

### 建议

目标网站必须运行在不可信环境：

```ts
webPreferences: {
  nodeIntegration: false,
  contextIsolation: true,
  sandbox: true,
  preload: minimalPreloadPath
}
```

目标网站不能直接访问：

- Node.js
- fs
- shell
- 本地文件
- 任意 IPC
- OpenBridge 内部 token

---

## 5.3 AgentApiServer

### 职责

向 AI Agent / 后端 / Codex / MCP 暴露操作接口。

### 推荐协议

第一阶段：

```text
HTTP + WebSocket
```

后续可扩展：

```text
MCP Server
```

### API 分类

```text
Browser API：打开网页、导航、刷新
Action API：点击、输入、滚动、按键
Observe API：截图、DOM、元素位置、可访问性树
Overlay API：鼠标动画、高亮、聚焦
Record API：开始录制、停止录制、导出视频
Artifact API：列出、上传、删除素材
```

---

## 6. AI Action API 设计

### 6.1 基础请求格式

```json
{
  "request_id": "req_001",
  "profile_id": "user-001",
  "action": "click_point",
  "params": {},
  "options": {
    "timeout_ms": 10000,
    "visual_effect": true,
    "record_timeline": true
  }
}
```

### 6.2 响应格式

```json
{
  "request_id": "req_001",
  "ok": true,
  "result": {},
  "state": {
    "url": "https://example.com",
    "title": "Example",
    "timestamp": 1720000000
  },
  "artifacts": []
}
```

### 6.3 open_url

```json
{
  "action": "open_url",
  "params": {
    "url": "https://example.com"
  }
}
```

### 6.4 screenshot

```json
{
  "action": "screenshot",
  "params": {
    "full_page": false,
    "format": "png"
  }
}
```

返回：

```json
{
  "ok": true,
  "artifacts": [
    {
      "type": "screenshot",
      "path": "artifacts/task-001/screenshots/0001.png"
    }
  ]
}
```

### 6.5 click_point

```json
{
  "action": "click_point",
  "params": {
    "x": 812,
    "y": 640,
    "button": "left"
  },
  "options": {
    "cursor_animation": "smooth_move",
    "click_effect": "ripple"
  }
}
```

### 6.6 click_selector

```json
{
  "action": "click_selector",
  "params": {
    "selector": "button.generate"
  },
  "options": {
    "highlight_before_click": true,
    "click_effect": "ripple"
  }
}
```

### 6.7 type_text

```json
{
  "action": "type_text",
  "params": {
    "text": "hello world",
    "delay_ms": 30
  },
  "options": {
    "keyboard_hint": true
  }
}
```

### 6.8 scroll

```json
{
  "action": "scroll",
  "params": {
    "delta_y": 720,
    "duration_ms": 600
  },
  "options": {
    "show_scroll_indicator": true
  }
}
```

### 6.9 get_page_state

```json
{
  "action": "get_page_state",
  "params": {
    "include_dom_text": true,
    "include_accessibility_tree": true,
    "include_screenshot": true
  }
}
```

返回给 Agent 的页面状态建议包括：

```text
url
title
viewport
screenshot_path
dom_text_summary
interactive_elements
accessibility_tree_excerpt
visible_buttons
visible_inputs
```

---

## 7. Overlay 动画层设计

## 7.1 目标

为录制视频增加清晰的操作可视化效果，让 AI 操作过程适合短视频素材使用。

需要支持：

```text
鼠标光圈
平滑移动轨迹
点击涟漪
按钮高亮
局部聚光灯
步骤编号气泡
键盘输入提示
滚动方向提示
局部 zoom-in，可选
敏感区域遮罩，可选
```

## 7.2 实现方式

推荐第一版使用独立透明 Overlay 层。

```text
Electron 主窗口
├─ WebContentsView：目标网站
└─ Overlay Layer：透明、pointer-events:none、始终覆盖目标网页区域
```

Overlay 不应该阻挡用户/Agent 的真实点击。

### 7.3 点击涟漪效果示例

```css
.click-ripple {
  position: absolute;
  width: 18px;
  height: 18px;
  border: 3px solid rgba(59, 130, 246, 0.95);
  border-radius: 999px;
  transform: translate(-50%, -50%) scale(0.3);
  animation: ripple 450ms ease-out forwards;
  pointer-events: none;
}

@keyframes ripple {
  to {
    opacity: 0;
    transform: translate(-50%, -50%) scale(3.2);
  }
}
```

### 7.4 元素高亮

通过 selector 找到目标元素 bounds：

```ts
const rect = await webContents.executeJavaScript(`
  (() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  })()
`);
```

然后在 Overlay 画高亮框。

注意事项：

- 处理 deviceScaleFactor。
- 处理 WebContentsView 在窗口中的偏移。
- 处理滚动后的坐标。
- 处理 iframe 元素，可作为后续增强。

---

## 8. Recorder 录屏引擎设计

## 8.1 第一版：录 Electron 当前窗口

链路：

```text
desktopCapturer.getSources({ types: ['window'] })
→ 找到当前 Electron 窗口 source
→ getUserMedia 获取 MediaStream
→ MediaRecorder 录制 WebM
→ FFmpeg 转 MP4
```

优点：

- 实现简单。
- Overlay 动画天然包含在录屏里。
- 对 MVP 最友好。

缺点：

- 可能录到客户端控制 UI。
- 窗口遮挡、缩放、最小化需要处理。
- 需要裁剪网页区域时要后处理。

### 推荐录制目标

```text
分辨率：1920x1080 或 1280x720
帧率：30fps
片段长度：10-30s
格式：WebM 原始文件 + MP4 转码文件
```

## 8.2 第二版：只录网页区域

方案一：窗口录制后裁剪。

```text
录整个窗口
→ 根据网页区域 bounds 裁剪
→ FFmpeg 输出网页区域视频
```

方案二：WebContents frame capture。

```text
webContents.beginFrameSubscription
→ 获取页面帧
→ Overlay 单独合成
→ FFmpeg 编码
```

## 8.3 音频策略

第一阶段建议不录网页原声。

视频工厂链路中音频主要来自：

```text
TTS 口播
字幕对齐
背景音乐
音效
```

如果后续需要网页原声，可以增加：

```text
系统 loopback audio
Electron desktopCapturer audio
tab/window audio capture
```

## 8.4 FFmpeg 转码

WebM 转 MP4 示例：

```bash
ffmpeg -y \
  -i input.webm \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -r 30 \
  -movflags +faststart \
  output.mp4
```

如果录制后需要裁剪网页区域：

```bash
ffmpeg -y \
  -i input.webm \
  -vf "crop=1280:720:320:180,fps=30" \
  -c:v libx264 \
  -pix_fmt yuv420p \
  output.mp4
```

---

## 9. Action Timeline 设计

所有 AI 操作都应该记录为时间线事件。

示例：

```json
{
  "task_id": "task-001",
  "profile_id": "user-001",
  "started_at": "2026-07-07T10:00:00+09:00",
  "viewport": {
    "width": 1920,
    "height": 1080,
    "device_scale_factor": 1
  },
  "events": [
    {
      "t": 0.0,
      "type": "open_url",
      "url": "https://example.com"
    },
    {
      "t": 1.2,
      "type": "cursor_move",
      "x": 812,
      "y": 640,
      "duration_ms": 300
    },
    {
      "t": 1.5,
      "type": "click",
      "x": 812,
      "y": 640,
      "effect": "ripple"
    },
    {
      "t": 2.1,
      "type": "highlight",
      "selector": ".dashboard-card",
      "duration_ms": 1200
    }
  ]
}
```

这个时间线后续可以服务于：

```text
视频素材切片
字幕对齐
镜头节奏控制
局部 zoom-in
自动生成讲解文案
失败回放
调试 Agent 行为
```

---

## 10. 文件与目录结构

推荐项目结构：

```text
openbridge-desktop/
├─ apps/
│  └─ desktop/
│     ├─ src/
│     │  ├─ main/
│     │  │  ├─ main.ts
│     │  │  ├─ agent-api/
│     │  │  ├─ browser/
│     │  │  ├─ profile/
│     │  │  ├─ recorder/
│     │  │  ├─ artifact/
│     │  │  └─ security/
│     │  │
│     │  ├─ renderer/
│     │  │  ├─ control-panel/
│     │  │  └─ overlay/
│     │  │
│     │  └─ preload/
│     │     ├─ control.preload.ts
│     │     └─ target.preload.ts
│     │
│     ├─ package.json
│     └─ electron.vite.config.ts
│
├─ packages/
│  ├─ action-schema/
│  ├─ timeline-schema/
│  └─ shared-types/
│
├─ scripts/
│  ├─ ffmpeg/
│  └─ dev/
│
└─ docs/
   ├─ architecture.md
   ├─ api.md
   └─ security.md
```

运行时数据目录：

```text
AppData/OpenBridgeDesktop/
├─ profiles/
├─ artifacts/
│  └─ task-001/
│     ├─ raw.webm
│     ├─ output.mp4
│     ├─ action_timeline.json
│     ├─ screenshots/
│     └─ metadata.json
└─ logs/
```

---

## 11. 安全设计

Electron 客户端可以做更多事，但安全风险也更高。必须从第一版开始约束。

### 11.1 远程网页安全

目标网站 WebContents 必须：

```text
nodeIntegration: false
contextIsolation: true
sandbox: true
```

目标网站不能直接访问：

```text
Node.js
fs
shell
本地文件路径
OpenBridge API token
任意 IPC 通道
```

### 11.2 IPC 安全

所有 IPC 必须：

```text
显式白名单
校验来源
校验参数 schema
禁止远程网页直接调用危险能力
禁止传递任意 JS 给主进程执行
```

### 11.3 Agent API 安全

本地 API Server 必须：

```text
只监听 127.0.0.1
启动时生成随机 token
所有请求携带 token
默认拒绝公网访问
限制文件读写目录
记录审计日志
```

### 11.4 录屏安全

录屏必须：

```text
有明显状态提示
用户可随时停止
默认只录客户端窗口或网页区域
敏感网站可配置禁录
支持手动遮罩敏感区域
```

---

## 12. MVP 开发阶段

## Phase 0：项目骨架

目标：跑起来 Electron + 控制面板 + 内置网页。

交付：

```text
Electron app 启动成功
左侧控制面板
右侧 WebContentsView 加载网站
基础日志系统
```

## Phase 1：Profile 与登录态

目标：用户在 Electron 内登录一次后，下次自动保持登录。

交付：

```text
创建 profile
切换 profile
persist session 生效
cookie/localStorage 保留
```

验收：

```text
打开目标网站 → 登录 → 关闭客户端 → 重开 → 仍保持登录
```

## Phase 2：AI Action API

目标：Agent 能操作网页。

交付：

```text
open_url
click_point
click_selector
type_text
press_key
scroll
wait_for_selector
screenshot
get_page_state
```

验收：

```text
通过 HTTP/WebSocket 连续完成一套网页操作流程
```

## Phase 3：Overlay 动画

目标：AI 操作有可视化效果。

交付：

```text
鼠标光圈
平滑移动
点击涟漪
元素高亮
滚动提示
键盘输入提示
```

验收：

```text
执行 click/type/scroll 时，画面中出现对应动画
```

## Phase 4：录屏

目标：录制当前 Electron 窗口并输出 MP4。

交付：

```text
record_start
record_stop
raw.webm
output.mp4
action_timeline.json
```

验收：

```text
录制 10 秒网页操作
视频包含网页、鼠标效果、点击动画
输出 MP4 可播放
```

## Phase 5：素材管理与上传

目标：将素材交给后端视频工厂。

交付：

```text
artifact list
artifact metadata
upload API
失败重试
任务 ID 绑定
```

验收：

```text
任务完成后，后端可拿到 video.mp4 + timeline.json + screenshots
```

---

## 13. 验收标准

MVP 完成标准：

```text
1. 可以打开任意普通网站。
2. 可以保存登录态。
3. 可以通过本地 API 操作页面。
4. 可以截图并返回路径。
5. 可以显示鼠标移动、点击涟漪、元素高亮。
6. 可以录制 10-30 秒操作视频。
7. 录制视频中包含 Overlay 效果。
8. 可以输出 MP4。
9. 可以输出 action_timeline.json。
10. 目标网站页面无法访问 Node/fs/shell。
```

推荐性能目标：

```text
720p 30fps：必须稳定
1080p 30fps：作为优化目标
单次录制长度：10-30 秒
首次 MVP 不追求 4K/60fps
```

---

## 14. 主要风险与解决方案

### 风险一：某些网站识别 Electron

解决：

```text
尽量使用正常 UA
减少自动化痕迹
用户手动登录一次
不绕过验证码
必要时保留 Chrome 插件模式作为补充
```

### 风险二：录屏帧率不稳

解决：

```text
第一版录整个窗口
目标先定 720p 30fps
1080p 做压测
FFmpeg 转码统一 CFR
复杂页面自动降级分辨率
```

### 风险三：Overlay 坐标不准

解决：

```text
统一使用 viewport 坐标
记录 deviceScaleFactor
记录 WebContentsView bounds
所有动画坐标都经过 CoordinateMapper
```

### 风险四：远程网页安全风险

解决：

```text
关闭 nodeIntegration
开启 contextIsolation
开启 sandbox
preload 最小化
IPC 白名单
Agent API token
```

### 风险五：与后端视频生成链路割裂

解决：

```text
所有操作记录 action_timeline.json
所有素材带 task_id
统一 artifact manifest
后端以 manifest 消费素材
```

---

## 15. 与 AI 视频工厂的关系

OpenBridge Desktop Client 不负责最终短视频剪辑，它负责生成“真实网页操作素材”。

完整链路：

```text
Website URL
→ OpenBridge Desktop Client
→ AI Agent 浏览网站
→ 功能点理解
→ 页面操作
→ 截图 / 录屏 / 时间线
→ 上传素材
→ 文案生成
→ TTS
→ 字幕对齐
→ Hyperframes / Remotion 编排
→ FFmpeg 输出最终视频
```

OpenBridge 输出给后端的核心文件：

```text
video.mp4：网页操作片段
action_timeline.json：操作时间线
screenshots/*.png：关键截图
metadata.json：页面、profile、viewport、录制参数
```

---

## 16. 给 Codex / 开发 Agent 的执行提示词

```text
我们要开发一个 Electron 桌面客户端 OpenBridge Desktop Client。

核心目标：
1. 内置 Chromium 浏览器加载目标网站。
2. 使用 Electron persist session 保存登录状态。
3. 提供本地 HTTP/WebSocket API，方便 AI Agent 操作网页。
4. 支持 open_url、click_point、click_selector、type_text、scroll、screenshot、start_recording、stop_recording 等动作。
5. 在网页上方显示透明 Overlay，用于鼠标光圈、点击涟漪、元素高亮、滚动提示等动画。
6. 第一版使用 desktopCapturer 录制 Electron 当前窗口，输出 WebM，再用 FFmpeg 转 MP4。
7. 每次操作都记录 action_timeline.json，后续交给视频生成系统使用。
8. 必须做好 Electron 安全隔离：目标网站 nodeIntegration=false、contextIsolation=true、sandbox=true，远程页面不能直接访问 Node、fs、shell 或任意 IPC。

请先实现 MVP：
- Electron 项目骨架
- 主窗口 + 控制面板 + WebContentsView
- persist profile
- 本地 Action API
- screenshot
- overlay click ripple
- recording start/stop
- artifact 输出目录
```

---

## 17. 推荐开发顺序

```text
1. Electron/Vite/TypeScript 项目初始化
2. 主窗口布局：左侧控制面板 + 右侧浏览器区域
3. WebContentsView 加载目标网站
4. persist session 保存登录态
5. 本地 HTTP/WebSocket API
6. open_url / screenshot / click_point
7. selector 定位与 click_selector
8. Overlay 鼠标光圈与点击涟漪
9. Action Timeline 记录
10. desktopCapturer 录屏
11. FFmpeg 转 MP4
12. artifacts 输出与上传
13. 安全审计和打包
```

---

## 18. 参考资料

- Electron Session API：`session.fromPartition('persist:xxx')` 用于持久化 session。
- Electron WebContents API：用于渲染、控制网页、截图、输入事件等。
- Electron WebContentsView：推荐的新网页承载方式。
- Electron desktopCapturer：用于捕获桌面、窗口、屏幕音视频源。
- Electron Security Checklist：远程内容必须关闭 Node 集成、开启上下文隔离和沙箱。

