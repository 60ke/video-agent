对，现在这个方向应该重新定义为：

> **网站功能种草视频生成系统**
> 不是 Agent Skill，也不是浏览器自动录屏系统，而是一个通用的网站功能视频生成模块。核心是：**文案驱动 + 网站截图素材 + 效果图素材库 + 图片重构 + 图片动效 + 多轨合成**。

# 1. 最终定位

系统目标：

```text
输入：
- 网站源码 / 本地运行的网站
- 网站功能配置
- 效果图素材库
- 文案生成模板
- 视频风格参数

输出：
- 一条快节奏竖屏功能种草视频
```

核心表达：

```text
这个网站有什么功能
  ↓
这些功能入口在哪里
  ↓
这些功能适合哪些行业
  ↓
它能生成什么样的效果图
  ↓
用户为什么应该用它
```

视频主体不再依赖录屏，而是：

```text
网站首页截图
功能入口截图
功能页面截图
功能操作关键截图
行业效果图素材库
图片动效包装
字幕 / 配音 / 音效 / BGM
固定片尾
```

---

# 2. 总体链路

```text
网站功能配置
  ↓
本机批量生成网站截图
  ↓
图片理解 / 图片重构 / 图片标准化
  ↓
效果图素材库检索
  ↓
DeepSeek 生成种草文案
  ↓
文案拆分成视频段落
  ↓
根据段落规划画面素材
  ↓
TTS 生成配音
  ↓
ASR / FunASR 做字幕时间轴与语速校验
  ↓
生成多轨 timeline.json
  ↓
Python 动效库 / Remotion 渲染视频
  ↓
FFmpeg 后处理
  ↓
输出成片
```

---

# 3. 模块划分

## 3.1 网站功能配置模块

不靠 Agent 随机分析网站，而是基于你们自己的源码和功能配置生成结构化信息。

配置内容：

```json
{
  "site_name": "科幻熊猫",
  "site_url": "https://kehuanxiongmao.com",
  "positioning": "广告人专用 AI 设计网站",
  "features": [
    {
      "feature_key": "text_to_image",
      "feature_name": "文生图",
      "sub_features": [
        "门头招牌",
        "文化墙",
        "景观小品",
        "美陈",
        "IP形象",
        "LOGO",
        "电商",
        "展台",
        "包装",
        "标识标牌",
        "VI",
        "海报",
        "活动物料"
      ],
      "page_route": "/text-to-image",
      "value": "一键生成广告行业各类设计效果图"
    },
    {
      "feature_key": "culture_wall_3d",
      "feature_name": "文化墙平面转3D",
      "page_route": "/culture-wall-3d",
      "value": "矢量图转3D效果图，再到CAD施工图"
    },
    {
      "feature_key": "ai_tools",
      "feature_name": "AI技能助手",
      "page_route": "/ai-tools",
      "value": "图片修复、多图合一、全能改图、转插画"
    }
  ]
}
```

---

## 3.2 网站截图生成模块

基于本机源码批量生成截图，而不是手工截图或录屏。

截图对象：

```text
首页截图
首页功能卡片截图
文生图入口截图
功能菜单截图
门头招牌页面截图
文化墙页面截图
行业下拉截图
场景选择截图
补充描述输入框截图
开始生成按钮截图
案例资源库截图
```

截图方式：

```text
本地启动前端项目
  ↓
Playwright 打开指定路由
  ↓
注入固定窗口尺寸
  ↓
滚动到指定区域
  ↓
按 selector 截图
  ↓
保存为结构化素材
```

截图配置：

```json
{
  "screenshots": [
    {
      "id": "home_main",
      "route": "/",
      "selector": "body",
      "viewport": {
        "width": 1728,
        "height": 972
      },
      "usage": "site_intro"
    },
    {
      "id": "feature_menu",
      "route": "/text-to-image",
      "selector": ".feature-menu",
      "usage": "feature_list"
    },
    {
      "id": "store_sign_form",
      "route": "/text-to-image?type=store_sign",
      "selector": ".left-form-panel",
      "usage": "operation_intro"
    },
    {
      "id": "industry_dropdown",
      "route": "/text-to-image?type=store_sign",
      "action": "open_industry_select",
      "selector": ".industry-dropdown",
      "usage": "industry_selection"
    }
  ]
}
```

---

## 3.3 图片重构模块

截图和效果图不直接进入视频，需要经过统一处理。

图片重构包括：

```text
裁剪主体区域
去除浏览器顶部栏
补全背景
统一圆角
统一阴影
统一边框
增强清晰度
局部放大
添加红框 / 箭头 / 高亮
生成视频可用卡片图
横图 / 竖图比例判断
生成模糊背景
生成封面图
```

输入：

```json
{
  "source": "screenshots/store_sign_form.png",
  "task": "highlight_ui",
  "highlight_targets": ["行业", "经营定位", "开始生成"],
  "output_size": "1080x1920"
}
```

输出：

```json
{
  "asset_id": "rebuild_store_sign_form_001",
  "path": "assets/rebuilt/store_sign_form_card.png",
  "type": "rebuilt_screenshot",
  "aspect": "portrait",
  "usage": "operation_intro"
}
```

图片重构可以分三类：

```text
1. 网站截图重构
   将网页截图变成适合短视频展示的卡片画面。

2. 效果图重构
   对素材库效果图做增强、补边、放大、清晰化和统一包装。

3. 视频封面重构
   基于强效果图 + 大标题生成短视频封面。
```

---

# 4. 效果图素材库

视频的核心说服力来自效果图素材库。

素材分类：

```text
功能维度：
- 门头招牌
- 文化墙
- 景观小品
- 美陈
- IP形象
- LOGO
- 电商
- 展台
- 包装
- 标识标牌
- VI
- 海报
- 活动物料

行业维度：
- 餐饮美食
- 住宿行业
- 零售行业
- 服务行业
- 娱乐休闲
- 汽车交通
- 医院
- 学校
- 企业
- 文旅
- 商场
- 党建
```

素材元数据：

```json
{
  "asset_id": "case_store_sign_food_001",
  "type": "case_image",
  "feature": "门头招牌",
  "industry": "餐饮美食",
  "scene": "火锅店",
  "style": "国潮",
  "aspect": "landscape",
  "width": 1920,
  "height": 1080,
  "path": "assets/cases/门头招牌/餐饮美食/001.png",
  "quality_score": 0.95,
  "tags": ["门头", "火锅", "国潮", "夜景", "发光字"]
}
```

---

# 5. 图片展示硬规则

视频是竖屏：

```text
画布：1080 × 1920
比例：9:16
```

所有图片最终展示形式只有两种。

## 5.1 竖屏图片

```text
竖屏图片：
- 左右铺满视频宽度
- 高度按比例自动适配
- 不横向留黑边
- 不拉伸变形
- 如果图片高度超过画布，可以做上下缓慢移动
```

模式：

```text
portrait_full_width
```

---

## 5.2 横屏图片

```text
横屏图片：
- 左右铺满视频宽度
- 高度按比例自动适配
- 上下居中
- 上下空白区域使用模糊背景 / 深色背景 / 品牌渐变背景
- 不强行裁掉主体
- 不拉伸变形
```

模式：

```text
landscape_full_width_center
```

---

## 5.3 自动判断

```text
if image_height / image_width >= 1.2:
    display_mode = portrait_full_width
else:
    display_mode = landscape_full_width_center
```

---

# 6. 动效规则

动效只改变进入、停留、切换方式，不改变最终展示规则。

支持动效：

```text
slide_left
slide_right
slide_up
slide_down
center_zoom_in
center_zoom_out
slow_zoom_in
slow_zoom_out
pan_vertical
pan_horizontal
fade_in
fade_out
quick_cut
before_after_switch
grid_to_single
single_to_grid
```

推荐使用：

```text
网站首页截图：
- center_zoom_in
- slow_zoom_in

功能菜单截图：
- center_zoom_in
- highlight_box
- arrow_callout

功能表单截图：
- zoom_to_area
- highlight_box
- label_callout

效果图素材：
- slide_left
- slide_right
- center_zoom_in
- slow_zoom_in
- quick_cut

行业合集：
- image_sequence
- grid_to_single
- quick_cut
```

---

# 7. 文案生成模块

使用 DeepSeek 根据配置生成种草文案。

输入：

```json
{
  "site_profile": {
    "name": "科幻熊猫",
    "positioning": "广告人专用 AI 设计网站"
  },
  "video_type": "功能种草",
  "duration": 30,
  "target_platform": "douyin",
  "selected_features": ["门头招牌", "文化墙", "美陈"],
  "selected_industries": ["餐饮美食", "企业", "商场"],
  "available_assets_summary": {
    "门头招牌": ["餐饮美食", "住宿行业", "零售行业"],
    "文化墙": ["医院", "学校", "企业"],
    "美陈": ["商场", "活动", "文旅"]
  }
}
```

输出不是纯文案，而是结构化脚本：

```json
{
  "title": "广告人常用的设计图，这个网站一键出",
  "voiceover": "做门头、文化墙、美陈还在熬夜改图？这个网站直接给广告人开了外挂。选门头招牌，填店名，选行业，餐饮、零售、住宿方案直接出。切到文化墙，企业、医院、学校风格也能一键生成。美陈打卡装置、商场活动场景，同样能批量出效果图。不用复杂提示词，说人话就行。想做广告设计图，直接上科幻熊猫。",
  "segments": [
    {
      "segment_id": "seg_001",
      "stage": "hook",
      "text": "做门头、文化墙、美陈还在熬夜改图？",
      "visual_type": "effect_case_fast_cut",
      "feature": ["门头招牌", "文化墙", "美陈"],
      "asset_query": {
        "type": "case_image",
        "count": 3
      },
      "duration_hint": 3
    },
    {
      "segment_id": "seg_002",
      "stage": "site_intro",
      "text": "这个网站直接给广告人开了外挂。",
      "visual_type": "website_homepage",
      "asset_query": {
        "type": "website_screenshot",
        "usage": "site_intro"
      },
      "duration_hint": 3
    },
    {
      "segment_id": "seg_003",
      "stage": "feature_demo",
      "text": "选门头招牌，填店名，选行业，餐饮、零售、住宿方案直接出。",
      "visual_type": "feature_ui_plus_cases",
      "feature": "门头招牌",
      "industry": ["餐饮美食", "零售行业", "住宿行业"],
      "asset_query": {
        "type": "case_image",
        "feature": "门头招牌",
        "count": 5
      },
      "duration_hint": 8
    }
  ]
}
```

---

# 8. 视频结构模板

## 8.1 单功能视频

```text
0-3s    强钩子：展示最终效果图快切
3-6s    网站首页 / 功能入口截图
6-9s    功能操作界面截图
9-20s   不同行业效果图展示
20-25s  操作步骤总结
25-30s  CTA + 固定片尾
```

适合：

```text
门头招牌
文化墙
美陈
IP形象
电商
海报
```

---

## 8.2 多功能合集视频

```text
0-3s    强钩子：多个效果图快速切换
3-6s    网站首页截图
6-10s   功能入口截图：门头、文化墙、美陈、LOGO、IP、电商
10-22s  各功能效果图轮播
22-26s  操作界面截图：上传、选择、描述、生成
26-30s  CTA + 固定片尾
```

---

## 8.3 行业垂直视频

```text
0-3s    行业痛点钩子
3-6s    网站首页 / 行业选择截图
6-12s   行业对应功能 1 效果图
12-18s  行业对应功能 2 效果图
18-24s  行业对应功能 3 效果图
24-27s  操作简单总结
27-30s  CTA + 片尾
```

示例：

```text
餐饮行业：
- 门头招牌
- 海报
- 电商详情页
- 包装
```

---

# 9. 多轨 timeline

多轨仍然是最终渲染核心。

```json
{
  "meta": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "duration": 30,
    "platform": "douyin"
  },
  "tracks": {
    "voice": [],
    "subtitle": [],
    "visual": [],
    "overlay": [],
    "sfx": [],
    "bgm": [],
    "ending": []
  }
}
```

visual track 示例：

```json
{
  "visual": [
    {
      "id": "clip_001_hook",
      "type": "image_sequence",
      "sources": [
        "assets/cases/门头招牌/餐饮美食/001.png",
        "assets/cases/文化墙/企业/001.png",
        "assets/cases/美陈/商场/001.png"
      ],
      "start": 0,
      "end": 3,
      "display_rule": "auto_by_aspect",
      "animation": "quick_cut",
      "title": "广告设计图，一键出效果"
    },
    {
      "id": "clip_002_home",
      "type": "image",
      "source": "assets/site/homepage_rebuilt.png",
      "start": 3,
      "end": 6,
      "display_rule": "auto_by_aspect",
      "animation": "center_zoom_in",
      "title": "广告人专用 AI 设计网站"
    },
    {
      "id": "clip_003_feature_menu",
      "type": "image",
      "source": "assets/site/feature_menu_rebuilt.png",
      "start": 6,
      "end": 9,
      "display_rule": "auto_by_aspect",
      "animation": "center_zoom_in",
      "overlays": [
        {
          "type": "highlight_box",
          "text": "门头招牌 / 文化墙 / 美陈"
        }
      ]
    },
    {
      "id": "clip_004_cases",
      "type": "image_sequence",
      "sources": [
        "assets/cases/门头招牌/餐饮美食/001.png",
        "assets/cases/门头招牌/零售行业/001.png",
        "assets/cases/门头招牌/住宿行业/001.png"
      ],
      "start": 9,
      "end": 17,
      "display_rule": "auto_by_aspect",
      "animation": "slide_left"
    }
  ]
}
```

---

# 10. 渲染实现

## 10.1 Python 方案

适合快速验证和简单动效。

可实现：

```text
图片缩放
图片平移
淡入淡出
左右滑动
上下滑动
字幕烧录
音频合成
片尾拼接
```

推荐组合：

```text
Pillow / OpenCV：图片预处理
MoviePy / FFmpeg：视频合成
ASS：字幕样式
FFmpeg：最终压缩与混音
```

---

## 10.2 Remotion 方案

适合正式版本。

可实现：

```text
组件化动效
图片序列展示
网站截图卡片
横竖图自适配
标题动画
标注框动画
关键词高亮
多轨音频
统一视觉风格
```

Remotion 组件：

```text
VideoComposition
ImageClip
ImageSequenceClip
WebsiteScreenshotClip
FeatureMenuClip
CaseShowcaseClip
SubtitleTrack
VoiceTrack
BgmTrack
SfxTrack
EndingClip
```

---

# 11. 处理顺序

```text
1. 配置网站功能表
2. 本机批量截图
3. 图片重构
4. 效果图素材入库
5. DeepSeek 生成结构化文案
6. TTS 生成配音
7. FunASR 生成字幕时间轴
8. 文案段落匹配图片素材
9. 生成 timeline.json
10. Python / Remotion 渲染
11. FFmpeg 后处理
12. 输出 final.mp4
```

---

# 12. 最终定义

你的当前方案应定义为：

> **网站功能截图 + 效果图素材库驱动的程序化种草视频生成系统。**

核心不是录屏，不是 Agent 操作，而是：

```text
文案规划
  ↓
图片素材匹配
  ↓
网站截图重构
  ↓
效果图重构
  ↓
图片动效编排
  ↓
多轨时间线合成
```

一句话总结：

> **用网站截图说明功能，用效果图素材库证明能力，用 DeepSeek 生成文案，用 TTS 和字幕确定节奏，最后用 Python / Remotion 把图片按统一展示规则和动效编排成快节奏竖屏种草视频。**
