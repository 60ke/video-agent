# CDP 网页录屏短视频素材采集方案

> 目标：使用 Chrome DevTools Protocol（CDP）控制浏览器、采集网页操作画面，并输出可用于短视频制作的网页录屏素材。  
> 本方案聚焦：网页自动操作、登录态保存、后台录制、鼠标/点击特效、广告浮层清理、素材导出。  
> 不依赖 Chrome 扩展作为主链路。

---

## 1. 我们要做什么

构建一个基于 CDP 的网页素材采集系统。

用户输入目标网站或选择已有登录环境后，系统自动打开网页，控制页面完成指定操作，同时录制网页画面，最终输出短视频制作所需素材。

整体链路：

```txt
目标网站 URL
→ 使用指定 Chrome Profile 打开网页
→ 保持登录状态
→ CDP 控制网页操作
→ 注入鼠标样式 / 点击动画 / 高亮特效
→ 屏蔽广告、Cookie 弹窗、浮动客服等干扰元素
→ CDP 后台采集网页画面帧
→ FFmpeg 编码成 MP4/WebM
→ 输出视频素材 + 操作时间轴 + 截图 + 元数据
```

---

## 2. 核心产物

每次采集任务输出一个素材包：

```txt
task-output/
├─ video.mp4
├─ timeline.json
├─ metadata.json
├─ screenshots/
│  ├─ step_001.png
│  ├─ step_002.png
│  └─ cover.png
└─ logs/
   ├─ cdp.log
   ├─ shield.log
   └─ recorder.log
```

### 2.1 video.mp4

网页操作录屏素材。

```txt
格式：MP4
编码：H.264
帧率：默认 30fps
分辨率：默认 1920×1080，可降级到 1280×720
用途：后续进入短视频合成流程
```

### 2.2 timeline.json

记录网页操作和视觉特效时间轴。

```json
[
  {
    "id": "evt_001",
    "type": "browser.open_url",
    "timestamp": 0.0,
    "payload": {
      "url": "https://example.com"
    }
  },
  {
    "id": "evt_002",
    "type": "overlay.click",
    "timestamp": 2.15,
    "duration": 0.48,
    "payload": {
      "x": 812,
      "y": 640,
      "effect": "ripple"
    }
  },
  {
    "id": "evt_003",
    "type": "browser.click_selector",
    "timestamp": 2.2,
    "payload": {
      "selector": "button.add-to-cart"
    }
  }
]
```

### 2.3 metadata.json

记录任务基础信息。

```json
{
  "taskId": "task_20260707_001",
  "url": "https://example.com",
  "profileId": "profile_example_admin",
  "resolution": "1920x1080",
  "fps": 30,
  "duration": 12.4,
  "recorder": "cdp_screencast",
  "output": "video.mp4",
  "createdAt": "2026-07-07T16:00:00+09:00"
}
```

---

## 3. 系统模块

```txt
CDP Web Capture System
├─ Profile Manager
├─ Chrome Launcher
├─ CDP Browser Controller
├─ Action Runner
├─ Overlay Runtime
├─ Content Shield
├─ CDP Recorder
├─ Frame Processor
├─ FFmpeg Encoder
├─ Asset Manager
└─ Task API
```

---

## 4. Profile Manager：登录态保存

### 4.1 目标

保存网站登录状态，让后续后台录制任务可以复用。

系统管理自己的 Chrome Profile。每个 Profile 对应一个独立的 Chrome `user-data-dir`：

```txt
profiles/
├─ profile_shopify_admin/
│  ├─ User Data/
│  └─ profile.json
│
├─ profile_cms_prod/
│  ├─ User Data/
│  └─ profile.json
│
└─ profile_demo_site/
   ├─ User Data/
   └─ profile.json
```

Chrome Profile 中保存：

```txt
Cookie
localStorage
IndexedDB
Service Worker Cache
站点权限
缓存
登录设备状态
```

### 4.2 创建 Profile

接口：

```json
{
  "action": "profile.create",
  "payload": {
    "name": "CMS Admin",
    "baseUrl": "https://cms.example.com"
  }
}
```

输出：

```json
{
  "profileId": "profile_cms_admin",
  "userDataDir": "D:/web-capture/profiles/profile_cms_admin/User Data"
}
```

### 4.3 手动登录流程

系统打开一个可见 Chrome 窗口，让用户完成登录。

启动命令示例：

```bash
chrome.exe ^
  --user-data-dir="D:\web-capture\profiles\profile_cms_admin\User Data" ^
  --remote-debugging-port=9222 ^
  --window-size=1280,900
```

流程：

```txt
1. 用户创建 Profile。
2. 系统启动可见 Chrome。
3. 用户手动登录目标网站。
4. 用户点击“验证登录”。
5. 系统用 CDP 检查登录状态。
6. 登录成功后，将 Profile 标记为 signed_in。
```

### 4.4 登录状态验证

支持多种检查方式：

```txt
1. URL 不包含 /login
2. 页面存在指定 selector
3. 页面文本包含账号名
4. Cookie 存在指定 key
5. localStorage 存在指定 key
```

接口：

```json
{
  "action": "profile.verify_login",
  "payload": {
    "profileId": "profile_cms_admin",
    "url": "https://cms.example.com",
    "checks": [
      {
        "type": "url_not_contains",
        "value": "/login"
      },
      {
        "type": "selector_exists",
        "selector": ".user-avatar"
      }
    ]
  }
}
```

### 4.5 后台任务复用 Profile

后台任务启动 headless Chrome，并使用同一个 `user-data-dir`。

```bash
chrome.exe ^
  --headless=new ^
  --user-data-dir="D:\web-capture\profiles\profile_cms_admin\User Data" ^
  --remote-debugging-port=9222 ^
  --window-size=1920,1080
```

注意：

```txt
同一个 Profile 不能同时被多个 Chrome 实例占用。
任务启动前需要检查 Profile lock。
```

---

## 5. Chrome Launcher

### 5.1 登录模式

用于用户手动登录。

```txt
模式：visible
窗口：可见
用途：用户登录、检查登录态、调试页面
```

启动参数：

```bash
chrome.exe ^
  --user-data-dir="<profileUserDataDir>" ^
  --remote-debugging-port=<port> ^
  --window-size=1280,900 ^
  --disable-notifications
```

### 5.2 后台采集模式

用于正式采集网页视频素材。

```txt
模式：headless
窗口：隐藏
用途：后台录制、批量任务、素材采集
```

启动参数：

```bash
chrome.exe ^
  --headless=new ^
  --user-data-dir="<profileUserDataDir>" ^
  --remote-debugging-port=<port> ^
  --window-size=1920,1080 ^
  --disable-notifications ^
  --autoplay-policy=no-user-gesture-required
```

### 5.3 推荐启动参数

```txt
--headless=new
--remote-debugging-port=<port>
--user-data-dir=<profile>
--window-size=1920,1080
--disable-notifications
--disable-background-timer-throttling
--disable-backgrounding-occluded-windows
--disable-renderer-backgrounding
--autoplay-policy=no-user-gesture-required
```

---

## 6. CDP Browser Controller

### 6.1 职责

通过 CDP 控制 Chrome 页面。

能力：

```txt
打开 URL
等待页面加载
点击坐标
点击 selector
输入文本
按键
滚动
执行受限 JS
截图
读取 DOM 文本
读取 Accessibility Tree
监听网络请求
监听 Console
监听页面生命周期
```

### 6.2 基础 Action

#### open_url

```json
{
  "action": "browser.open_url",
  "payload": {
    "url": "https://example.com",
    "waitUntil": "network_idle"
  }
}
```

执行逻辑：

```txt
Page.navigate
等待 Page.lifecycleEvent
等待 network idle
记录 timeline
```

#### click_point

```json
{
  "action": "browser.click_point",
  "payload": {
    "x": 812,
    "y": 640,
    "button": "left",
    "overlay": {
      "clickEffect": "ripple"
    }
  }
}
```

执行逻辑：

```txt
1. overlay.moveCursor
2. overlay.click 动画
3. Input.dispatchMouseEvent mousePressed
4. Input.dispatchMouseEvent mouseReleased
5. 记录 timeline
```

#### click_selector

```json
{
  "action": "browser.click_selector",
  "payload": {
    "selector": "button.add-to-cart",
    "waitVisible": true,
    "overlay": {
      "highlight": true,
      "clickEffect": "ripple"
    }
  }
}
```

执行逻辑：

```txt
1. Runtime.evaluate 查找元素
2. 计算元素中心坐标
3. overlay.highlightElement
4. overlay.moveCursor
5. overlay.click
6. Input.dispatchMouseEvent
7. 记录 timeline
```

#### type_text

```json
{
  "action": "browser.type_text",
  "payload": {
    "selector": "input[name='q']",
    "text": "wireless headphones",
    "delay": 30
  }
}
```

执行逻辑：

```txt
1. 点击输入框
2. Input.dispatchKeyEvent 按字符输入
3. 记录 timeline
```

#### scroll

```json
{
  "action": "browser.scroll",
  "payload": {
    "deltaY": 720,
    "duration": 500
  }
}
```

执行逻辑：

```txt
Input.dispatchMouseEvent mouseWheel
或 Runtime.evaluate window.scrollBy
记录 timeline
```

#### screenshot

```json
{
  "action": "browser.screenshot",
  "payload": {
    "format": "png",
    "fullPage": false
  }
}
```

执行逻辑：

```txt
Page.captureScreenshot
保存到 screenshots/
记录 timeline
```

---

## 7. Action Runner

### 7.1 任务格式

一个采集任务由多个 action 构成。

```json
{
  "taskId": "task_demo_001",
  "profileId": "profile_demo",
  "url": "https://example.com",
  "recording": {
    "enabled": true,
    "resolution": "1920x1080",
    "fps": 30,
    "format": "mp4"
  },
  "actions": [
    {
      "action": "browser.open_url",
      "payload": {
        "url": "https://example.com"
      }
    },
    {
      "action": "browser.click_selector",
      "payload": {
        "selector": ".pricing-link",
        "overlay": {
          "highlight": true,
          "clickEffect": "ripple"
        }
      }
    },
    {
      "action": "browser.scroll",
      "payload": {
        "deltaY": 800,
        "duration": 600
      }
    }
  ]
}
```

### 7.2 执行流程

```txt
1. 加载任务
2. 启动 Chrome
3. 连接 CDP
4. 设置 viewport
5. 注入 Overlay Runtime
6. 注入 Content Shield
7. 启动 Recorder
8. 顺序执行 actions
9. 停止 Recorder
10. 编码视频
11. 输出素材包
```

---

## 8. Overlay Runtime：鼠标样式与点击动画

### 8.1 目标

给网页录屏增加可视化引导，让素材更适合短视频。

支持：

```txt
鼠标光圈
点击涟漪
点击闪光
元素高亮
聚焦 spotlight
文字标注
操作路径
```

### 8.2 注入方式

通过 CDP `Runtime.evaluate` 注入 Shadow DOM Overlay。

结构：

```html
<cdp-capture-overlay-root>
  <style>
    /* overlay styles */
  </style>
  <div class="ob-cursor"></div>
  <div class="ob-ripple-layer"></div>
  <div class="ob-focus-layer"></div>
  <div class="ob-annotation-layer"></div>
</cdp-capture-overlay-root>
```

要求：

```txt
position: fixed
inset: 0
z-index: 2147483647
pointer-events: none
不影响目标网页真实交互
```

### 8.3 Overlay Action

#### 设置鼠标样式

```json
{
  "action": "overlay.set_cursor_style",
  "payload": {
    "visible": true,
    "size": 32,
    "color": "#1DCEFF",
    "halo": {
      "enabled": true,
      "radius": 28,
      "pulse": true
    }
  }
}
```

#### 移动鼠标

```json
{
  "action": "overlay.move_cursor",
  "payload": {
    "x": 812,
    "y": 640,
    "duration": 420,
    "easing": "easeOutCubic"
  }
}
```

#### 点击动画

```json
{
  "action": "overlay.click",
  "payload": {
    "x": 812,
    "y": 640,
    "effect": {
      "type": "ripple",
      "color": "#1DCEFF",
      "duration": 480,
      "rings": 2
    }
  }
}
```

#### 元素高亮

```json
{
  "action": "overlay.highlight_element",
  "payload": {
    "selector": "button.add-to-cart",
    "duration": 1200,
    "style": {
      "type": "outline",
      "color": "#00B8FF",
      "width": 2,
      "radius": 12,
      "glow": true
    }
  }
}
```

### 8.4 自定义特效 DSL

允许 AI 下发结构化特效，而不是任意 JS。

```json
{
  "action": "overlay.custom_effect",
  "payload": {
    "name": "softBlueRipple",
    "target": {
      "x": 820,
      "y": 520
    },
    "layers": [
      {
        "type": "circle",
        "from": {
          "scale": 0.2,
          "opacity": 0.9
        },
        "to": {
          "scale": 3.2,
          "opacity": 0
        },
        "style": {
          "borderColor": "#1DCEFF",
          "borderWidth": 3
        },
        "duration": 480,
        "easing": "easeOutCubic"
      }
    ]
  }
}
```

安全要求：

```txt
默认不允许 AI 执行任意 JS。
只允许结构化 DSL。
高级模式可以允许受限 CSS，但只能作用于 overlay root。
```

---

## 9. Content Shield：网页干扰清理

### 9.1 目标

清理影响录屏的网页干扰元素。

处理对象：

```txt
浮动广告
Cookie 弹窗
Newsletter 弹窗
客服气泡
遮挡层
自动弹窗
广告脚本
跟踪脚本
```

### 9.2 能力分层

```txt
Content Shield
├─ Network Blocker
├─ Cosmetic Filter
├─ DOM Cleaner
├─ Popup Blocker
└─ Rule Manager
```

### 9.3 Network Blocker

通过 CDP `Fetch` 或 `Network` 拦截广告请求。

规则示例：

```json
{
  "id": "block-doubleclick",
  "type": "network",
  "pattern": "*://*.doubleclick.net/*",
  "action": "block"
}
```

```json
{
  "id": "block-ads-script",
  "type": "network",
  "pattern": "*://*/ads/*",
  "resourceTypes": ["script", "image", "xhr"],
  "action": "block"
}
```

### 9.4 Cosmetic Filter

通过 CSS 隐藏干扰元素。

```css
[class*="ad-"],
[id*="ad-"],
[class*="ads"],
[id*="ads"],
[class*="advert"],
[id*="advert"],
[class*="sponsor"],
[id*="sponsor"],
[class*="cookie"],
[id*="cookie"],
[class*="gdpr"],
[id*="gdpr"],
[class*="chat-widget"],
[class*="intercom"],
[class*="crisp"] {
  display: none !important;
}
```

### 9.5 DOM Cleaner

通过 MutationObserver 持续清理动态插入元素。

```js
(() => {
  const selectors = [
    '.newsletter-modal',
    '#cookie-banner',
    '.floating-ad',
    '[aria-label="Advertisement"]'
  ];

  function hideMatched() {
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach(el => {
        el.setAttribute('data-cdp-capture-hidden', 'true');
        el.style.setProperty('display', 'none', 'important');
      });
    }
  }

  hideMatched();

  const observer = new MutationObserver(() => {
    hideMatched();
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true
  });
})();
```

### 9.6 Shield Action

#### 开启 Shield

```json
{
  "action": "shield.set_enabled",
  "payload": {
    "enabled": true,
    "mode": "balanced"
  }
}
```

模式：

```txt
off
safe
balanced
strict
```

#### 隐藏指定元素

```json
{
  "action": "shield.hide_element",
  "payload": {
    "selector": "#cookie-banner",
    "scope": "current_page",
    "reason": "obstructs recording"
  }
}
```

#### 添加 CSS 规则

```json
{
  "action": "shield.add_cosmetic_rule",
  "payload": {
    "domain": "example.com",
    "selector": ".floating-ad",
    "action": "hide"
  }
}
```

#### 扫描浮层

```json
{
  "action": "shield.scan_floating_layers",
  "payload": {
    "minAreaRatio": 0.05,
    "includeFixed": true,
    "includeSticky": true
  }
}
```

---

## 10. CDP Recorder：网页画面采集

### 10.1 录制目标

通过 CDP `Page.startScreencast` 采集页面帧。

录制对象：

```txt
Chrome 页面渲染结果
包含网页内容
包含注入的 Overlay 特效
包含被 Shield 清理后的页面
```

不包含：

```txt
系统桌面
浏览器外部窗口
网页原声音频
```

### 10.2 录制流程

```txt
1. Page.startScreencast
2. 监听 Page.screencastFrame
3. 立即 Page.screencastFrameAck
4. 解码 base64 JPEG
5. 保存 frame buffer + timestamp
6. 按目标 fps 对齐
7. 补帧 / 丢帧
8. 管道输入 FFmpeg
9. 输出 MP4
```

### 10.3 推荐参数

#### 默认 1080p

```json
{
  "format": "jpeg",
  "quality": 72,
  "maxWidth": 1920,
  "maxHeight": 1080,
  "everyNthFrame": 1
}
```

#### 稳定 720p

```json
{
  "format": "jpeg",
  "quality": 80,
  "maxWidth": 1280,
  "maxHeight": 720,
  "everyNthFrame": 1
}
```

### 10.4 帧处理

CDP 发送的是不稳定帧流，不应直接假设等于 30fps。

需要做 CFR 输出：

```txt
目标时间轴：
0ms, 33.33ms, 66.66ms, 100ms ...

CDP 实际帧：
0ms, 31ms, 70ms, 142ms ...

处理：
缺帧复制上一帧
过密帧丢弃
最终输出固定 30fps
```

### 10.5 FFmpeg 编码

可以将处理后的帧通过管道输入 FFmpeg。

```bash
ffmpeg -y ^
  -f image2pipe ^
  -framerate 30 ^
  -i - ^
  -c:v libx264 ^
  -preset veryfast ^
  -crf 20 ^
  -pix_fmt yuv420p ^
  output.mp4
```

---

## 11. Task API 设计

### 11.1 创建采集任务

```json
{
  "action": "task.create",
  "payload": {
    "profileId": "profile_cms_admin",
    "url": "https://cms.example.com",
    "recording": {
      "resolution": "1920x1080",
      "fps": 30,
      "format": "mp4"
    },
    "shield": {
      "enabled": true,
      "mode": "balanced"
    },
    "overlay": {
      "cursor": "neon",
      "clickEffect": "ripple"
    }
  }
}
```

### 11.2 运行任务

```json
{
  "action": "task.run",
  "payload": {
    "taskId": "task_001",
    "actions": [
      {
        "action": "browser.open_url",
        "payload": {
          "url": "https://cms.example.com"
        }
      },
      {
        "action": "browser.click_selector",
        "payload": {
          "selector": ".create-button",
          "overlay": {
            "highlight": true,
            "clickEffect": "ripple"
          }
        }
      }
    ]
  }
}
```

### 11.3 停止任务

```json
{
  "action": "task.stop",
  "payload": {
    "taskId": "task_001"
  }
}
```

### 11.4 查询任务状态

```json
{
  "action": "task.status",
  "payload": {
    "taskId": "task_001"
  }
}
```

返回：

```json
{
  "taskId": "task_001",
  "status": "recording",
  "duration": 8.2,
  "framesCaptured": 246,
  "droppedFrames": 5,
  "output": null
}
```

---

## 12. 短视频素材要求

### 12.1 画面要求

```txt
网页内容清晰
鼠标轨迹可见
点击动作明显
关键区域有高亮
浮动广告/弹窗尽量清理
录制时长控制在 5-30 秒
```

### 12.2 输出尺寸

默认横屏素材：

```txt
1920×1080
30fps
MP4
```

短视频后续可裁剪为：

```txt
1080×1920
9:16
```

采集阶段建议保留横屏全量信息，后续由视频合成系统做：

```txt
局部放大
镜头裁剪
转场
字幕
口播
封面
```

### 12.3 素材切片

任务可以按操作步骤切片：

```txt
clip_001_open_page.mp4
clip_002_click_add_cart.mp4
clip_003_scroll_features.mp4
```

每个切片对应 timeline：

```json
{
  "clipId": "clip_002",
  "start": 3.2,
  "end": 6.8,
  "actions": ["overlay.click", "browser.click_selector"]
}
```

---

## 13. 错误处理

### 13.1 登录失效

```txt
1. 停止任务。
2. 标记 Profile 为 login_required。
3. 提示用户打开可见窗口重新登录。
4. 登录验证成功后重试任务。
```

### 13.2 页面加载失败

```txt
1. 重试 URL。
2. 降低 Shield 强度。
3. 保存失败截图。
4. 记录 network log。
```

### 13.3 录制帧率不足

```txt
1. 降低到 720p。
2. 降低 JPEG quality。
3. 降低动画复杂度。
4. 输出 droppedFrames 到 metadata。
```

### 13.4 Shield 误杀

```txt
1. 当前站点关闭 Shield。
2. 降低模式：strict → balanced → safe。
3. 从规则中移除 selector。
4. 重新加载页面。
```

---

## 14. MVP 范围

第一版只实现必要链路：

```txt
1. Profile 创建
2. 可见 Chrome 登录
3. Headless Chrome CDP 启动
4. CDP 打开网页
5. click_selector / type_text / scroll
6. Overlay 鼠标光圈和点击涟漪
7. 基础 CSS Shield
8. Page.startScreencast 采集
9. FFmpeg 输出 MP4
10. timeline.json
11. metadata.json
```

第一版不做：

```txt
1. Chrome 扩展
2. 完整 uBlock 规则兼容
3. 网页原声音频采集
4. 多浏览器支持
5. 多 Profile 并发运行
6. 复杂视频剪辑
```

---

## 15. 后续增强

```txt
1. EasyList 子集广告规则
2. 自定义 Overlay DSL
3. 自动识别浮动遮挡层
4. 分步骤自动切片
5. 录制质量评分
6. 1080p/720p 自动降级
7. 多任务队列
8. Profile 过期检测
9. 与 TTS / 字幕 / 视频合成系统打通
10. 9:16 自动裁剪建议
```

---

## 16. 给开发模型的实现提示词

```txt
请实现一个基于 Chrome DevTools Protocol 的网页录屏素材采集系统。
目标不是浏览器插件，也不是普通桌面录屏，而是用 CDP 后台控制 Chrome，采集网页操作画面，输出短视频素材。

系统需要包含：
1. Profile Manager：创建并管理 Chrome user-data-dir，用于保存登录状态。
2. Chrome Launcher：支持可见登录模式和 headless 后台采集模式。
3. CDP Browser Controller：支持 open_url、click_selector、click_point、type_text、scroll、screenshot。
4. Overlay Runtime：通过 CDP 注入 Shadow DOM，实现鼠标光圈、点击涟漪、元素高亮。
5. Content Shield：通过 CSS 和 MutationObserver 隐藏广告、Cookie 弹窗、浮动客服等遮挡元素。
6. CDP Recorder：使用 Page.startScreencast 获取页面帧。
7. Frame Processor：根据 timestamp 补帧/丢帧，输出固定 30fps。
8. FFmpeg Encoder：将帧流编码为 MP4。
9. Asset Manager：输出 video.mp4、timeline.json、metadata.json、screenshots。

第一版不要做 Chrome 扩展，不要做完整 uBlock，不要做网页原声音频。
第一版重点是跑通：登录 Profile → CDP 控制网页 → Overlay 点击动画 → Shield 清理浮层 → CDP 录屏 → FFmpeg 输出 MP4。
```
