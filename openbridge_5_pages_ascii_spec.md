# OpenBridge Desktop 五页 UI ASCII 实现说明

> 用途：给不支持多模态输入的模型或前端开发者使用。  
> 目标：根据 5 张设计图实现 Web/Electron 前端页面。  
> 页面：Browser、Settings、Recorder、Projects、Assets。  
> 风格：暗色桌面客户端、深蓝/靛蓝背景、电蓝/青色高亮、圆角卡片、轻量发光、简洁布局。

---

## 0. 全局设计原则

### 0.1 产品定位

OpenBridge Desktop 是一个 Electron 桌面客户端，用于：

- 嵌入浏览器并保存登录状态。
- 提供 AI 操作接口，让 Agent 可以打开网页、点击、输入、滚动、截图、录制。
- 提供鼠标光圈、点击涟漪、焦点框等 Overlay 效果。
- 录制网页操作素材，并导出视频、截图、Timeline JSON、报告等资产。

### 0.2 页面分工

```txt
Browser   = 主工作台：浏览网页 + AI 操作 + 简单录制状态
Settings  = 配置页：登录 Session、录制参数、Overlay、Agent 行为
Recorder  = 录制页：录制预览、录制控制、最近录制
Projects  = 项目页：管理自动化流程项目
Assets    = 资产页：管理录屏、截图、Timeline、报告文件
```

重要原则：

```txt
Browser 页面不要塞复杂配置。
Settings 页面不要显示完整浏览器工作区。
Recorder 页面只处理录制与导出。
Projects 页面只管理项目。
Assets 页面只管理素材。
```

---

## 1. 全局 App Shell

五个页面共享同一个 App Shell。

### 1.1 全局布局 ASCII

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│  [App Icon] OpenBridge Desktop                                  ─  □  ×      │
│             AI Browser Automation                                           │
├───────────────┬──────────────────────────────────────────────────────────────┤
│               │                                                              │
│   Sidebar     │                    Page Content                              │
│               │                                                              │
│   Browser     │                                                              │
│   Projects    │                                                              │
│   Recorder    │                                                              │
│   Assets      │                                                              │
│   Settings    │                                                              │
│               │                                                              │
│               │                                                              │
│ [Agent        │                                                              │
│  Connected]   │                                                              │
│               │                                                              │
└───────────────┴──────────────────────────────────────────────────────────────┘
```

### 1.2 推荐尺寸

```txt
窗口比例：16:10
设计基准：1586 × 992
顶部标题栏高度：96px
左侧 Sidebar 宽度：206px
主内容左右边距：24px-32px
卡片圆角：14px-20px
按钮圆角：12px-16px
```

### 1.3 视觉 Token

```css
:root {
  --bg: #040c1f;
  --panel: #081736;
  --panel-2: #0a1f46;
  --card: #091b41;
  --card-2: #0d2656;
  --border: #1f5bab;

  --primary: #0077ff;
  --primary-2: #00b8ff;
  --cyan: #1dceff;
  --green: #23da8f;
  --red: #ff4f71;
  --yellow: #ffc43a;
  --purple: #825cff;

  --text: #ecf6ff;
  --muted: #8aa4cd;
  --muted-2: #6e86ae;

  --radius-sm: 10px;
  --radius-md: 14px;
  --radius-lg: 18px;
  --radius-xl: 24px;

  --glow-blue: 0 0 24px rgba(0, 119, 255, 0.35);
  --glow-cyan: 0 0 20px rgba(29, 206, 255, 0.35);
}
```

### 1.4 Sidebar 状态

```txt
未选中：
  icon + label，浅蓝灰文字，无背景。

选中：
  圆角矩形蓝色发光背景。
  icon 和 label 使用白色或高亮蓝白色。
```

### 1.5 全局底部状态卡

Sidebar 底部有小状态卡：

```txt
┌────────────────────┐
│ ● Agent Connected  │
│    ~~~~~~~~        │
└────────────────────┘
```

说明：

- 绿色圆点表示 Agent 通道已连接。
- 小波形仅作为动态/科技感装饰。
- 每页都保持一致。

---

# 2. Browser 页面

## 2.1 页面职责

Browser 是主工作台，用于：

- 加载目标网页。
- 让用户/Agent 在嵌入浏览器中操作页面。
- 展示 AI Prompt、Recent Actions。
- 显示简单的录制状态和导出入口。
- 展示 Overlay 效果，例如鼠标光圈、点击涟漪。

不在此页做复杂设置。配置入口放到 Settings。

## 2.2 Browser 页面 ASCII

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Icon] OpenBridge Desktop                                      ─  □  ×       │
│        AI Browser Automation                                                │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│               │                                              │               │
│  ● Browser    │ ┌──────────────────────────────────────────┐ │ ┌───────────┐ │
│    Projects   │ │ Browser Tab: Aurora Headphones - Premium │ │ │ AI Agent  │ │
│    Recorder   │ ├──────────────────────────────────────────┤ │ │      ●    │ │
│    Assets     │ │ ← → ↻  🔒 https://shop...                 │ │ ├───────────┤ │
│    Settings   │ ├──────────────────────────────────────────┤ │ │ Prompt    │ │
│               │ │                                          │ │ │ textarea  │ │
│               │ │  NOVA AUDIO       Home Shop Collections  │ │ │           │ │
│               │ │                                          │ │ │ 0/1000  ➤ │ │
│               │ │ ┌──────────────┐   Aurora Headphones     │ │ ├───────────┤ │
│               │ │ │ thumbnails   │   $299.00               │ │ │ Recent    │ │
│               │ │ │              │   ★★★★★ (reviews)       │ │ │ Actions   │ │
│               │ │ │  Product     │   Color: ● ○ ●          │ │ │           │ │
│               │ │ │  Image       │                         │ │ │ 1 Navigate│ │
│               │ │ │              │   ┌─────────────────┐   │ │ │ 2 Click   │ │
│               │ │ └──────────────┘   │ Add to Cart     │◉  │ │ │ 3 View    │ │
│               │ │                    └─────────────────┘   │ │ │           │ │
│               │ │                       ▲ cursor ripple     │ │ ├───────────┤ │
│               │ │                                          │ │ │ Run Agent │ │
│               │ └──────────────────────────────────────────┘ │ └───────────┘ │
│               │ ┌──────────────────────────────────────────┐ │               │
│               │ │ ● Recording 00:01:24 | timeline | Export │ │               │
│               │ └──────────────────────────────────────────┘ │               │
│ [Agent        │                                              │               │
│  Connected]   │                                              │               │
└───────────────┴──────────────────────────────────────────────┴───────────────┘
```

## 2.3 Browser 页面模块说明

### A. 中央 Browser Workspace

```txt
位置：主内容左中区域，占页面最大空间。
结构：
  Browser Shell
    - Tab bar
    - Address bar
    - Web preview/content
```

Browser Shell 需要模拟真实浏览器：

```txt
Tab:
  [icon] Aurora Headphones - Premium  ×     +

Address:
  ← → ↻  🔒 https://shop.novaudio.com/products/aurora-headphones       ☆ ⋮
```

内部示例网页是电商商品页：

```txt
品牌：NOVA AUDIO
导航：Home / Shop / Collections / About / Support
商品：Aurora Headphones
价格：$299.00
按钮：Add to Cart
```

开发时可以用静态 mock 网页，也可以 iframe/webview 嵌入真实网页。

### B. Overlay 效果

Browser 页面只展示少量 Overlay，避免复杂：

```txt
1. 鼠标光圈 Cursor Highlight
2. 点击涟漪 Click Ripple
```

示例：

```txt
Add to Cart 按钮上显示蓝色涟漪 + 光标。
```

实现建议：

```html
<div class="browser-viewport">
  <iframe class="embedded-browser"></iframe>
  <div class="overlay-layer">
    <div class="cursor cursor-active"></div>
    <div class="click-ripple"></div>
  </div>
</div>
```

Overlay 层要求：

```css
.overlay-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 20;
}
```

### C. 右侧 AI Agent Panel

右侧只保留三块：

```txt
1. Prompt 输入区
2. Recent Actions 短列表
3. Run Agent 主按钮
```

Recent Actions 最多显示 3-5 条，避免过载。

示例数据：

```txt
1 Navigate to novaudio.com
2 Click on Shop menu
3 View product: Aurora Headphones
```

### D. 底部 Recording Strip

```txt
┌──────────────────────────────────────────────┐
│ ● Recording  00:01:24  | timeline | Export   │
└──────────────────────────────────────────────┘
```

说明：

- 只展示当前录制状态。
- Timeline 是简化条，不做复杂编辑器。
- Export 按钮用于快速导出当前录制片段。

---

# 3. Settings 页面

## 3.1 页面职责

Settings 专门配置系统行为，不承载浏览器主工作区。

配置项包括：

```txt
Session & Login
Recording
Overlay Effects
Agent Behavior
```

## 3.2 Settings 页面 ASCII

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Icon] OpenBridge Desktop                                      ─  □  ×       │
│        AI Browser Automation                                                │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│               │ Settings                                     │ Preview &     │
│    Browser    │ Configure your OpenBridge Desktop experience │ Summary   ●   │
│    Projects   │                                              │               │
│    Recorder   │ ┌──────────────────────────────────────────┐ │ ┌───────────┐ │
│    Assets     │ │ 1 Session & Login                         │ │ │ mini      │ │
│  ● Settings   │ │  [user] Persistent Profile          ON    │ │ │ preview   │ │
│               │ │  [folder] Saved Sessions     Ask me ▾    │ │ │ cursor    │ │
│               │ │  [shield] Login Status     Signed in ✓   │ │ └───────────┘ │
│               │ └──────────────────────────────────────────┘ │               │
│               │ ┌──────────────────────────────────────────┐ │ Current       │
│               │ │ 2 Recording                               │ │ Configuration │
│               │ │  Resolution 1920×1080 ▾                  │ │               │
│               │ │  FPS        30 ▾                         │ │ Profile       │
│               │ │  Folder     Videos ▾                     │ │ Persistent    │
│               │ │  Format     MP4 ▾                        │ │               │
│               │ └──────────────────────────────────────────┘ │ Recording     │
│               │ ┌──────────────────────────────────────────┐ │ 1920×1080     │
│               │ │ 3 Overlay Effects                         │ │ 30 FPS / MP4  │
│               │ │  Cursor Highlight  ON                     │ │               │
│               │ │  Click Ripple      ON                     │ │ Overlay       │
│               │ │  Focus Outline     ON                     │ │ Cursor/Ripple │
│               │ └──────────────────────────────────────────┘ │               │
│               │ ┌──────────────────────────────────────────┐ │ Agent         │
│               │ │ 4 Agent Behavior                          │ │ Auto-run...   │
│               │ │  Auto-run Agent      ON                   │ │               │
│               │ │  Wait Network Idle   ON                   │ │               │
│               │ │  Stealth Mode        OFF                  │ │               │
│               │ └──────────────────────────────────────────┘ │               │
│               │ [Reset to Default]              [Save Changes]│              │
│ [Agent        │                                              │               │
│  Connected]   │                                              │               │
└───────────────┴──────────────────────────────────────────────┴───────────────┘
```

## 3.3 Settings 页面模块说明

### A. Session & Login

字段：

```txt
Persistent Profile
  类型：Switch
  说明：开启后保留 cookie、localStorage、IndexedDB、缓存等登录态。

Saved Sessions
  类型：Select
  选项：Ask me / Restore last session / Always new session

Login Status
  类型：Status Pill
  状态：Signed in / Not signed in
```

### B. Recording

字段：

```txt
Resolution:
  1920×1080 / 1280×720 / Custom

FPS:
  30 / 24 / 60

Output Folder:
  Videos / Project Folder / Custom

Export Format:
  MP4 / WebM
```

### C. Overlay Effects

字段：

```txt
Cursor Highlight:
  显示鼠标光圈。

Click Ripple:
  点击时显示涟漪。

Focus Outline:
  Agent 操作元素时显示焦点框。
```

### D. Agent Behavior

字段：

```txt
Auto-run Agent:
  启动任务后自动执行。

Wait for Network Idle:
  每次页面跳转后等待网络空闲。

Stealth Mode:
  降低自动化识别特征。
```

### E. 右侧 Preview & Summary

只做摘要，不显示完整浏览器：

```txt
小预览卡：模拟 cursor/ripple 效果。
当前配置摘要：
  Profile
  Recording
  Overlay
  Agent
```

---

# 4. Recorder 页面

## 4.1 页面职责

Recorder 专门负责录制与导出：

```txt
- 录制预览
- 开始/停止/暂停
- 当前时长
- 分辨率、FPS、格式
- 最近录制片段
- 简化 Action Timeline
```

## 4.2 Recorder 页面 ASCII

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Icon] OpenBridge Desktop                                      ─  □  ×       │
│        AI Browser Automation                                                │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│               │ Recorder                                     │ Recent        │
│    Browser    │ Capture browser actions as clean video assets│ Recordings    │
│    Projects   │                                              │               │
│  ● Recorder   │ ┌──────────────────────────────────────────┐ │ ┌───────────┐ │
│    Assets     │ │ Large Recording Preview                   │ │ │ clip 1    │ │
│    Settings   │ │ ┌──────────────────────────────────────┐ │ │ │ Ready ↗   │ │
│               │ │ │ Browser preview thumbnail             │ │ ├───────────┤ │
│               │ │ │                                      │ │ │ clip 2    │ │
│               │ │ │   Product page / cursor ripple        │ │ │ Ready ↗   │ │
│               │ │ │                       ◉ cursor        │ │ ├───────────┤ │
│               │ │ └──────────────────────────────────────┘ │ │ │ clip 3    │ │
│               │ └──────────────────────────────────────────┘ │ │ Encoding  │ │
│               │ ┌──────────────────────────────────────────┐ │ └───────────┘ │
│               │ │ ● Recording 00:01:24 | action timeline   │ │               │
│               │ │ blue markers: click | scroll | type      │ │               │
│               │ └──────────────────────────────────────────┘ │               │
│               │                                              │               │
│               │ ┌──────────┐ ┌──────┐ ┌──────┐ ┌──────────┐ │               │
│               │ │Resolution│ │ FPS  │ │Format│ │ Source   │ │               │
│               │ │1920×1080 │ │ 30   │ │ MP4  │ │ Browser  │ │               │
│               │ └──────────┘ └──────┘ └──────┘ └──────────┘ │               │
│               │                                              │ [Start        │
│               │                                              │  Recording]   │
│ [Agent        │                                              │               │
│  Connected]   │                                              │               │
└───────────────┴──────────────────────────────────────────────┴───────────────┘
```

## 4.3 Recorder 页面模块说明

### A. Recording Preview

大卡片，显示录制内容预览。

预览中不需要真实完整网页，可以是缩略模拟：

```txt
Browser frame
  - 地址栏
  - 页面缩略图
  - cursor ripple
```

用途：

```txt
让用户确认当前正在录哪个窗口/区域。
```

### B. Recording Controls

放在预览下方或右下：

```txt
Start Recording
Stop
Pause
Timer: 00:01:24
Export
```

第一版可只做：

```txt
Start Recording
Export
```

### C. Action Timeline

简化的横向条：

```txt
| click | scroll | type | click |
```

建议事件类型：

```txt
open_url
click
type
scroll
screenshot
record_start
record_stop
```

Timeline 用于导出 `timeline.json`。

### D. Recent Recordings

右侧列表：

```txt
checkout-flow.mp4
  00:01:24 • 38 MB • Ready

search-demo.mp4
  00:00:42 • 16 MB • Ready

login-flow.webm
  00:00:35 • 12 MB • Encoding
```

每条提供：

```txt
Preview icon
File name
Duration / size
Status
Open / Export icon
```

---

# 5. Projects 页面

## 5.1 页面职责

Projects 用于管理自动化流程项目。

项目代表一组目标网站、任务步骤、录制配置、素材和导出结果的集合。

## 5.2 Projects 页面 ASCII

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Icon] OpenBridge Desktop                                      ─  □  ×       │
│        AI Browser Automation                                                │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│               │ Projects                         [New Project]│ Project       │
│    Browser    │ Create and manage automation flows            │ Summary       │
│  ● Projects   │                                              │               │
│    Recorder   │ ┌──────────────────────────────────────────┐ │ ┌───────────┐ │
│    Assets     │ │ Search projects...     [All][Active][Draft]│ │ │ 4 Projects │ │
│    Settings   │ └──────────────────────────────────────────┘ │ │ 2 active   │ │
│               │                                              │ └───────────┘ │
│               │ ┌────────────────────┐ ┌────────────────────┐ │               │
│               │ │ E-Commerce Checkout│ │ SaaS Onboarding    │ │ Template      │
│               │ │ product search...  │ │ signup flow...     │ │               │
│               │ │ [Active] 6 tasks   │ │ [Draft] 4 tasks    │ │ 1 Open URL    │
│               │ │ Modified Today     │ │ Modified Yesterday │ │ 2 Record      │
│               │ │              Open  │ │              Open  │ │ 3 Export      │
│               │ └────────────────────┘ └────────────────────┘ │               │
│               │ ┌────────────────────┐ ┌────────────────────┐ │               │
│               │ │ Analytics Demo     │ │ CMS Publishing     │ │               │
│               │ │ chart filters...   │ │ publishing demo... │ │               │
│               │ │ [Active] 8 tasks   │ │ [Paused] 5 tasks   │ │               │
│               │ │              Open  │ │              Open  │ │ [Use Template]│
│               │ └────────────────────┘ └────────────────────┘ │               │
│ [Agent        │                                              │               │
│  Connected]   │                                              │               │
└───────────────┴──────────────────────────────────────────────┴───────────────┘
```

## 5.3 Projects 页面模块说明

### A. 项目列表

项目卡片字段：

```txt
Project name
Description
Status: Active / Draft / Paused
Task count
Last modified time
Open button
```

示例项目：

```txt
E-Commerce Checkout
Automate product search, add-to-cart and checkout recording.
Status: Active
Tasks: 6
Modified: Today
```

### B. 搜索和筛选

顶部筛选：

```txt
Search projects...
All
Active
Draft
```

第一版只做 UI，不一定需要真实过滤逻辑。

### C. 右侧 Project Summary

```txt
总项目数
状态统计
默认流程模板
Use Template 按钮
```

默认模板步骤：

```txt
1 Open URL
2 Record Actions
3 Export Assets
```

### D. 项目数据结构建议

```ts
type Project = {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'draft' | 'paused';
  tasks: number;
  modifiedAt: string;
  defaultUrl?: string;
  profileId?: string;
};
```

---

# 6. Assets 页面

## 6.1 页面职责

Assets 管理所有输出资产：

```txt
Video: MP4 / WebM
Screenshot: PNG / JPG
Timeline: JSON
Report: PDF
```

## 6.2 Assets 页面 ASCII

```txt
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Icon] OpenBridge Desktop                                      ─  □  ×       │
│        AI Browser Automation                                                │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│               │ Assets                              [Import] │ Asset Details │
│    Browser    │ Organize recordings, screenshots and exports │               │
│    Projects   │                                              │ ┌───────────┐ │
│    Recorder   │ ┌──────────────────────────────────────────┐ │ │ preview   │ │
│  ● Assets     │ │ Videos 18 | Screenshots 42 | Timelines 12│ │ │    ▶      │ │
│    Settings   │ │ Exports 9              Search assets...  │ │ └───────────┘ │
│               │ └──────────────────────────────────────────┘ │               │
│               │                                              │ checkout-flow │
│               │ ┌────────────┐ ┌────────────┐ ┌────────────┐ │ .mp4          │
│               │ │ video mp4  │ │ screenshot │ │ timeline   │ │               │
│               │ │ thumbnail  │ │ thumbnail  │ │ json       │ │ Type Video    │
│               │ │ name/meta  │ │ name/meta  │ │ name/meta  │ │ Duration      │
│               │ └────────────┘ └────────────┘ └────────────┘ │ Resolution    │
│               │ ┌────────────┐ ┌────────────┐ ┌────────────┐ │ Timeline      │
│               │ │ video mp4  │ │ screenshot │ │ report pdf │ │               │
│               │ │ thumbnail  │ │ thumbnail  │ │ thumbnail  │ │ [Export][Open]│
│               │ └────────────┘ └────────────┘ └────────────┘ │               │
│               │                                              │               │
│               │ ┌──────────────────────────────────────────┐ │               │
│               │ │ Drop files here to add assets             │ │               │
│               │ │ Supported: MP4, WebM, PNG, JPG, JSON, PDF │ │               │
│               │ │                                  [Upload] │ │               │
│               │ └──────────────────────────────────────────┘ │               │
│ [Agent        │                                              │               │
│  Connected]   │                                              │               │
└───────────────┴──────────────────────────────────────────────┴───────────────┘
```

## 6.3 Assets 页面模块说明

### A. 顶部统计卡

```txt
Videos: 18
Screenshots: 42
Timelines: 12
Exports: 9
```

### B. Asset Grid

每个 Asset 卡片显示：

```txt
Thumbnail
File name
Metadata
Type pill
```

示例：

```txt
checkout-flow.mp4
Video • 00:01:24
MP4
```

资产类型：

```txt
MP4
WebM
PNG
JPG
JSON
PDF
```

### C. 右侧 Asset Details

点击资产后右侧显示：

```txt
Preview
File name
Created time
Size
Type
Duration
Resolution
Timeline actions count
Export button
Open button
```

### D. 底部 Upload Area

```txt
Drop files here to add assets
Supported: MP4, WebM, PNG, JPG, JSON, PDF
[Upload]
```

---

# 7. 关键组件清单

## 7.1 AppShell

```txt
AppShell
  Header
  Sidebar
  MainContent
```

Props：

```ts
type AppShellProps = {
  activePage: 'browser' | 'projects' | 'recorder' | 'assets' | 'settings';
  children: React.ReactNode;
};
```

## 7.2 Sidebar

```txt
SidebarItem
  icon
  label
  active
```

导航顺序固定：

```txt
Browser
Projects
Recorder
Assets
Settings
```

## 7.3 Button

按钮类型：

```txt
PrimaryButton：蓝色发光
SecondaryButton：深色描边
DangerButton：红色录制状态
IconButton：仅图标
```

## 7.4 Card

所有面板使用统一 Card：

```css
.card {
  background: linear-gradient(180deg, var(--card), var(--panel));
  border: 1px solid rgba(31, 91, 171, 0.75);
  border-radius: 18px;
  box-shadow: inset 0 1px rgba(255,255,255,0.04);
}
```

## 7.5 Toggle

```txt
ON:
  蓝色背景，白色圆点在右侧。

OFF:
  深灰背景，浅色圆点在左侧。
```

## 7.6 Select

```txt
深色圆角输入框
右侧下拉箭头
```

## 7.7 Overlay

Overlay 组件包括：

```txt
CursorHighlight
ClickRipple
FocusOutline
```

### CursorHighlight ASCII

```txt
        ◉
       /|
      / |
```

实际实现：

```css
.cursor-halo {
  width: 48px;
  height: 48px;
  border-radius: 999px;
  border: 2px solid var(--cyan);
  box-shadow: 0 0 24px rgba(29,206,255,.55);
  animation: pulse 1.2s ease-in-out infinite;
}
```

### ClickRipple

```css
.click-ripple {
  position: absolute;
  width: 18px;
  height: 18px;
  border: 3px solid var(--cyan);
  border-radius: 999px;
  transform: translate(-50%, -50%) scale(.35);
  animation: ripple 460ms ease-out forwards;
}

@keyframes ripple {
  to {
    opacity: 0;
    transform: translate(-50%, -50%) scale(3.2);
  }
}
```

---

# 8. 页面路由建议

```txt
/
  → Browser

/projects
  → Projects

/recorder
  → Recorder

/assets
  → Assets

/settings
  → Settings
```

Electron 内部可以用 React Router 或手写状态切换。

---

# 9. 数据结构建议

## 9.1 Action Timeline

```ts
type ActionEvent = {
  id: string;
  type:
    | 'open_url'
    | 'click'
    | 'type'
    | 'scroll'
    | 'screenshot'
    | 'record_start'
    | 'record_stop';
  label: string;
  timestamp: number;
  meta?: Record<string, any>;
};
```

## 9.2 Recording

```ts
type RecordingAsset = {
  id: string;
  fileName: string;
  duration: number;
  sizeBytes: number;
  format: 'mp4' | 'webm';
  resolution: string;
  fps: number;
  status: 'ready' | 'encoding' | 'failed';
  createdAt: string;
  timelineId?: string;
};
```

## 9.3 Asset

```ts
type Asset = {
  id: string;
  type: 'video' | 'screenshot' | 'timeline' | 'report';
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  createdAt: string;
  previewUrl?: string;
  metadata?: Record<string, any>;
};
```

## 9.4 Settings

```ts
type AppSettings = {
  session: {
    persistentProfile: boolean;
    savedSessions: 'ask' | 'restore_last' | 'new_each_time';
    loginStatus: 'signed_in' | 'signed_out';
  };
  recording: {
    resolution: '1920x1080' | '1280x720' | 'custom';
    fps: 24 | 30 | 60;
    outputFolder: string;
    exportFormat: 'mp4' | 'webm';
  };
  overlay: {
    cursorHighlight: boolean;
    clickRipple: boolean;
    focusOutline: boolean;
  };
  agent: {
    autoRun: boolean;
    waitForNetworkIdle: boolean;
    stealthMode: boolean;
  };
};
```

---

# 10. 开发实现优先级

## 10.1 MVP 必须实现

```txt
1. AppShell + Sidebar
2. Browser 页面静态 UI
3. Settings 页面静态 UI
4. Recorder 页面静态 UI
5. Projects 页面静态 UI
6. Assets 页面静态 UI
7. 页面切换
8. 统一主题样式
9. Overlay 动画组件
```

## 10.2 第二阶段

```txt
1. Electron WebContentsView 嵌入真实网页
2. Persistent Session 保存登录态
3. Agent HTTP/WebSocket API
4. webContents 控制点击、输入、滚动
5. 截图功能
6. 录制当前窗口
7. 导出 MP4/WebM
```

## 10.3 第三阶段

```txt
1. Timeline JSON 导出
2. 素材资产库
3. 项目持久化
4. 录制片段裁剪
5. 自定义 Overlay 颜色/大小/动画
6. 多 Profile 管理
```

---

# 11. 给代码模型的实现提示词

可以把下面这段直接给不支持图片的代码模型：

```txt
请实现一个名为 OpenBridge Desktop 的 Electron/React 风格前端 UI 原型。
它有 5 个页面：Browser、Settings、Recorder、Projects、Assets。
使用暗色深蓝主题、电蓝/青色高亮、圆角卡片、轻微发光效果。
不要做复杂企业仪表盘，整体要简洁、留白充足。

全局：
- 顶部标题栏显示 OpenBridge Desktop / AI Browser Automation。
- 左侧 Sidebar 固定导航：Browser、Projects、Recorder、Assets、Settings。
- Sidebar 底部显示 Agent Connected 状态。
- 每页共享同样 AppShell。

Browser 页面：
- 中央是大尺寸嵌入浏览器区域，模拟商品页。
- 右侧是简单 AI Agent 面板，包含 prompt 输入、Recent Actions、Run Agent 按钮。
- 底部是简单 Recording strip，包含 Recording 状态、时间、timeline、Export。
- 浏览器页面只展示少量鼠标光圈/点击涟漪，不放复杂配置。

Settings 页面：
- 主内容是 Settings 表单，包含四组卡片：Session & Login、Recording、Overlay Effects、Agent Behavior。
- 右侧是 Preview & Summary 小卡片。
- 底部有 Reset to Default 和 Save Changes。
- 不显示完整浏览器工作区。

Recorder 页面：
- 主内容是大录制预览卡。
- 预览下方是 Recording 状态、Action Timeline。
- 底部有 Resolution、FPS、Format、Source 几个小卡片。
- 右侧是 Recent Recordings 列表和 Start Recording 按钮。

Projects 页面：
- 顶部有 Search 和筛选按钮。
- 中央是项目卡片网格。
- 右侧是 Project Summary 和默认流程模板。
- 顶部右侧有 New Project 按钮。

Assets 页面：
- 顶部显示 Videos、Screenshots、Timelines、Exports 统计和搜索框。
- 中央是资产网格，包含视频、截图、JSON、PDF 卡片。
- 右侧是 Asset Details。
- 底部是 Drop files upload 区域。

请先实现静态 UI，组件结构清晰，可后续接入 Electron、WebContentsView、录屏、Agent API。
```

---

# 12. 验收标准

实现后应满足：

```txt
1. 五个页面视觉风格一致。
2. Browser 与 Settings 明显分离。
3. Browser 页面主区域是浏览器，不是配置面板。
4. Settings 页面只做配置，不出现完整浏览器。
5. Recorder 页面专注录制。
6. Projects 页面专注项目管理。
7. Assets 页面专注素材管理。
8. 页面信息密度适中，不复杂、不拥挤。
9. 右侧辅助面板不抢主内容。
10. 鼠标光圈和点击涟漪可作为独立 Overlay 组件复用。
```
