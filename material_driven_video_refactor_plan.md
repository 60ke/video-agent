# 素材库驱动的视频生成重构方案

## 1. 目标定位

本项目下一阶段应重构为：

```text
素材库驱动的网站功能种草视频生成系统
```

核心目标不是复用历史链路，也不是兼容录屏方案，而是稳定产出观感更好的竖屏视频：

```text
前端源码定位功能
-> CDP 采集真实网站截图和结果图
-> GPT image 制作可直接入镜的 9:16 图片素材
-> 素材库按功能、行业、用途组织
-> 文案和语音决定时间轴
-> 多轨 video_project 编排图片、动效、字幕、音频
-> FFmpeg 稳定渲染成片
```

判断标准只有一个：能提高最终视频质量、稳定性、可控性，就留下；不能，就舍弃。

## 2. 当前能力取舍

### 保留

- `Minimax T2A`：保留。它已经解决配音和 word 级字幕时间轴，不再回到 FunASR。
- `GPT image`：保留。用于把截图、结果图整理成可直接进入竖屏视频的关键帧。
- `simple_ffmpeg`：保留并升级。它足够确定、可控，适合作为主渲染器。
- `video_project.json`：保留概念，但大幅升级 schema，不需要兼容旧字段。
- 前端源码 registry：保留。它是功能定位和模块分类的稳定来源。
- CDP 自动化：保留，但只作为素材采集和真实性验证工具。

### 舍弃

- 录屏作为视频主链路：舍弃。
- `browser-recording-fit-width` 作为标准视频视觉：舍弃。
- 基于录屏 camera track 的局部镜头：舍弃。
- `crop-focus`、`zoom_to_area`、任意局部裁剪修复：舍弃。
- 视频生成时现场跑浏览器、现场截图、现场等待结果：舍弃。
- 为历史 demo case 或旧链路保留兼容逻辑：舍弃。

录屏可以作为调试证据临时保留，但不进入标准视频生成链路。

## 3. 新系统分层

### 3.1 素材工厂层

负责生产素材，不负责生成视频。

输入：

```text
前端源码 / 模块 registry
目标网站登录态
CDP 任务配置
真实生成结果
GPT image 配置
```

输出：

```text
模块截图
路径标记图
输入参数截图
真实结果图
GPT 9:16 关键帧
```

### 3.2 视频生产层

负责使用素材库生成视频，不再操作网页。

输入：

```text
截图素材文件
素材 groups
视频目标
文案模板
视频模板
Minimax 配音配置
```

输出：

```text
video_script.json
subtitle_track.json
video_project.json
final.mp4
contact_sheet.jpg
render_qa.json
```

## 4. 目录设计

建议新增素材库目录：

```text
assets/
  sites/
    柯幻熊猫_网站_主页_原始桌面截图.jpg
    柯幻熊猫_文生图_门头招牌_功能入口截图.png
    柯幻熊猫_文生图_门头招牌_参数面板截图.png
    柯幻熊猫_文生图_活动美陈_功能入口截图.png
    柯幻熊猫_文生图_活动美陈_参数面板截图.png
    ...
```

`cases/` 只用于一次具体视频项目，不再承载长期素材沉淀。

## 5. 素材命名规范

素材命名要支持文件名快速检索。

网站和功能模块本身是中文语义，素材文件名应采用中文优先，避免“活动美陈 -> activity_decoration -> 活动美陈”的来回转换造成信息损耗。英文 slug 只作为 `asset_id`、脚本字段、跨系统稳定键使用；人直接浏览文件夹和图片文件时，应能从中文文件名看懂素材内容。

### 5.1 效果图素材

格式：

```text
<站点>_<一级来源>_<功能模块>_<行业>_<场景>_<序号>_<素材类型>_<横竖属性>_<版本>.png
```

示例：

```text
柯幻熊猫_文生图_门头招牌_餐饮美食_火锅店_001_结果图_横图_v1.png
柯幻熊猫_文生图_门头招牌_零售行业_服装店_002_结果图_横图_v1.png
柯幻熊猫_文生图_活动美陈_商场活动_新春_001_结果图_横图_v1.png
柯幻熊猫_文生图_VI_零售行业_品牌视觉_001_结果图_竖图_v1.png
```

字段含义：

```text
柯幻熊猫            站点
文生图              一级来源
门头招牌            功能模块
餐饮美食            行业
火锅店              场景或子类
001                 序号
结果图              素材类型
横图                横竖属性
v1                  版本
```

### 5.2 网站截图素材

格式：

```text
<站点>_<一级来源或网站>_<功能模块或页面>_<步骤>_<序号>_<状态或版本>.png
```

示例：

```text
柯幻熊猫_网站_主页_原始桌面截图.jpg
柯幻熊猫_网站_主页_002_入口标记.png
柯幻熊猫_文生图_门头招牌_功能页_001_空表单.png
柯幻熊猫_文生图_门头招牌_输入参数_001_干净版.png
柯幻熊猫_文生图_门头招牌_生成按钮_002_标记规划.png
柯幻熊猫_文生图_门头招牌_结果页_001_证据截图.png
柯幻熊猫_文生图_门头招牌_结果图_001_GPT竖屏关键帧.png
```

关键区分：

```text
result              最终效果图，可用于展示能力
result_page_evidence 网页结果页证据，不作为最终效果图
form_params         输入参数截图
route_page          功能路由页面截图
callout             红框/箭头标记图
gpt_9x16            已经由 GPT image 处理为视频关键帧
```

### 5.3 文件名与稳定键的关系

文件名中文优先，但程序内部仍保留稳定英文键（asset_id），方便脚本检索：

```json
{
  "asset_id": "kx_tti_signboard_food_hotpot_001_result_landscape_v1",
  "filename": "柯幻熊猫_文生图_门头招牌_餐饮美食_火锅店_001_结果图_横图_v1.png",
  "site": "kehuanxiongmao",
  "module": "signboard",
  "module_label": "门头招牌",
  "industry": "food",
  "industry_label": "餐饮美食"
}
```

原则：

- 文件名给人看，中文优先。
- `asset_id` 给程序用，ASCII 稳定。
- 中文 label 必须保留在程序内存对象中，不允许只保存英文 slug。
- 后续按文件名检索时，优先匹配中文 tokens；按脚本自动筛选时，使用内存对象字段。

## 6. 素材元数据结构（内存对象）

采集过程中的元数据（坐标、字段、按钮位置等）以内存对象形式返回给调用方，不再写入 JSON 文件。结构示例如下：

示例：

```json
{
  "schema_version": 1,
  "site": "kehuanxiongmao",
  "generated_at": "2026-07-08T00:00:00+08:00",
  "assets": [
    {
      "asset_id": "kx_tti_signboard_food_hotpot_001_result_landscape_v1",
      "site": "kehuanxiongmao",
      "source_level_1": "text_to_image",
      "module": "signboard",
      "module_label": "门头招牌",
      "route": "/textToImage/signboard",
      "industry": "food",
      "industry_label": "餐饮美食",
      "scene": "hotpot",
      "scene_label": "火锅店",
      "asset_kind": "result_image",
      "visual_state": "gpt_9x16",
      "aspect": "landscape",
      "path": "柯幻熊猫_文生图_门头招牌_结果图_横图_v1.png",
      "source_path": "柯幻熊猫_文生图_门头招牌_结果图_横图_v1_raw.png",
      "display_rule": "landscape_full_width_center",
      "usage": ["hook", "fast_cut", "result_showcase", "gallery"],
      "claims": ["门头招牌效果图", "餐饮行业", "真实生成结果"],
      "tags": ["门头", "餐饮", "火锅", "商业设计"],
      "quality": {
        "ai_verified": true,
        "readable": true,
        "usable_for_video": true,
        "score": 0.92
      },
      "truth": {
        "source": "cdp_result_capture",
        "receipt_id": "receipt_signboard_20260708_001",
        "can_claim_real_generation": true
      }
    }
  ]
}
```

### 6.1 `asset_kind` 白名单

```text
site_home
feature_entry
feature_menu
feature_route_page
feature_form_params
generate_callout
generating_state
result_page_evidence
result_image
case_image
gpt_keyframe
cover_candidate
```

其中：

- `result_image` 和 `case_image` 可以用于能力展示。
- `result_page_evidence` 只能用于证明流程，不能作为结果主画面。
- `gpt_keyframe` 是可直接进入视频的 9:16 素材。

### 6.2 `visual_state` 白名单

```text
raw
clean
callout
gpt_9x16
rejected
archived
```

标准视频只允许使用 `gpt_9x16`，除非素材本身已经是合格的 `prepared_9x16`。

## 7. Material Groups Schema

`material_groups.json` 用于多图展示和模板选择。

示例：

```json
{
  "schema_version": 1,
  "groups": [
    {
      "group_id": "kx_tti_signboard_food_results",
      "site": "kehuanxiongmao",
      "source_level_1": "text_to_image",
      "module": "signboard",
      "module_label": "门头招牌",
      "industry": "food",
      "industry_label": "餐饮美食",
      "group_kind": "result_gallery",
      "asset_ids": [
        "kx_tti_signboard_food_hotpot_001_result_landscape_v1",
        "kx_tti_signboard_food_cafe_002_result_landscape_v1",
        "kx_tti_signboard_food_bbq_003_result_landscape_v1"
      ],
      "usage": ["hook_fast_cut", "industry_showcase", "gallery"],
      "min_video_duration": 3.0,
      "recommended_clip_type": "image_sequence"
    }
  ]
}
```

视频 planner 应优先选择 group，而不是一张张随机挑图。

## 8. 素材生产链路

### 8.1 模块发现

以源码 registry 为准：

```text
references/site_profiles/kehuanxiongmao_text_to_image_modules.json
```

对每个模块读取：

```text
id
label
route
page_title
source_type
primary_task_type
component
```

CDP 只做 live verification，不负责临场猜测模块。

### 8.2 CDP 素材采集

CDP 任务应支持无录屏模式：

```json
{
  "recording": { "enabled": false },
  "captureMode": "material_package"
}
```

采集内容：

```text
首页截图
文生图入口截图
模块菜单截图
功能页面空表单截图
功能参数填写截图
生成按钮标记截图
结果页证据截图
真实结果图裁剪/导出
```

CDP 输出：

```text
screenshots/
results/
timeline.json
generation_receipts.json
```

不输出 `video.mp4`，不生成 recording camera track。

CDP 在新链路中的职责只到“截图和结构化坐标证据”为止。它不负责把红框、鼠标圆圈、箭头等视觉标记永久烧进最终图片。原因是 CDP overlay 直接截图容易受页面比例、滚动、缩放影响，最终进入 9:16 视频时还需要重新排版，早早烧进红框会导致位置、粗细、比例失真。

CDP 应输出两类内容：

```text
1. 干净截图：原始网页状态，不带最终视频标记。
2. 标记规划：目标元素坐标、标记类型、文字说明、语义用途。
```

推荐在内存对象中记录 `callouts`：

```json
{
  "asset_id": "kx_tti_signboard_form_001_params_clean",
  "filename": "柯幻熊猫_文生图_门头招牌_输入参数_001_干净版.png",
  "callouts": [
    {
      "type": "highlight_box",
      "target_label": "行业选择",
      "box": {"x": 0.08, "y": 0.28, "w": 0.24, "h": 0.08},
      "text": "选择行业"
    },
    {
      "type": "pulse_ring",
      "target_label": "开始生成",
      "box": {"x": 0.10, "y": 0.78, "w": 0.20, "h": 0.07},
      "text": "开始生成"
    }
  ]
}
```

`box` 使用原始截图坐标的归一化比例，而不是像素值。这样 GPT image 或后续渲染器在重排到 9:16 时仍能理解目标区域。

### 8.3 GPT image 关键帧生成

GPT image 的职责：

```text
把素材整理为可直接进入 1080x1920 视频的关键帧
```

它不负责：

```text
做动画
发明新 UI
改写网站文字
重新设计结果图
生成不存在的功能状态
```

GPT image 需要接收 CDP 产出的 `callouts` 规划，并决定最终标记如何在 9:16 关键帧里呈现。

标记处理分两种：

```text
静态标记：红框、箭头、标签文字，可以由 GPT image 直接做进关键帧。
动态标记：鼠标圆圈、点击脉冲、呼吸高亮，应保留为 overlay_track，由渲染器做动画。
```

推荐规则：

- 需要解释路径的截图：GPT image 可以做红框、箭头、轻量标签。
- 需要表现点击感的截图：GPT image 只保证目标按钮清晰，鼠标圆圈和点击脉冲交给 `overlay_track`。
- 结果图：默认不加红框、箭头、鼠标圈，除非文案明确讲某个细节。
- 标记不能遮挡关键 UI 文本。
- 标记不能引入不存在的 UI 元素或改变原网页内容。

提示词原则：

```text
Use the uploaded image as the only source of truth.
Only adjust format, framing, scale, spacing, and composition for a 1080x1920 vertical video.
Do not invent UI, logos, text, products, icons, or extra elements.
Preserve the original Chinese text and visual meaning.
If callout metadata is provided, render only the requested lightweight red boxes, arrows, or labels around the target regions. Keep callouts aligned with the original UI target after vertical layout adaptation.
```

## 9. 视频 Project Schema

旧 `video_project.json` 可以直接升级，不必兼容旧字段。

建议新结构：

```json
{
  "schema_version": 2,
  "meta": {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "platform": "douyin",
    "video_type": "single_feature_seed"
  },
  "assets": [],
  "voice_track": {},
  "subtitle_track": {},
  "visual_track": [],
  "overlay_track": [],
  "audio_tracks": [],
  "ending_track": {},
  "qa_rules": {}
}
```

### 9.1 Visual Clip 类型

`visual_track` 支持：

```text
image
image_sequence
image_grid
site_flow_steps
result_gallery
before_after
cover_frame
```

### 9.2 单图 clip

```json
{
  "id": "vis_002",
  "start": 3.2,
  "end": 5.8,
  "clip_type": "image",
  "asset_ids": ["kx_site_home_002_callout_entry"],
  "display_rule": "prepared_9x16",
  "motion": {
    "name": "whole_frame_push_in",
    "amount": 0.022
  },
  "transition_in": {
    "name": "crossfade",
    "duration": 0.18
  }
}
```

### 9.3 多图序列 clip

```json
{
  "id": "vis_004",
  "start": 8.4,
  "end": 13.2,
  "clip_type": "image_sequence",
  "asset_ids": [
    "kx_tti_signboard_food_hotpot_001_result_landscape_v1",
    "kx_tti_signboard_retail_fashion_001_result_landscape_v1",
    "kx_tti_signboard_hotel_001_result_landscape_v1"
  ],
  "display_rule": "landscape_full_width_center",
  "sequence": {
    "mode": "quick_cut",
    "min_item_duration": 0.8,
    "max_item_duration": 1.6,
    "transition": "slide_left"
  },
  "motion": {
    "name": "whole_frame_push_in",
    "amount": 0.018
  }
}
```

### 9.4 网站路径 clip

```json
{
  "id": "vis_003",
  "start": 5.8,
  "end": 8.4,
  "clip_type": "site_flow_steps",
  "asset_ids": [
    "kx_site_home_002_callout_entry",
    "kx_tti_signboard_menu_001_callout",
    "kx_tti_signboard_route_001_page_empty"
  ],
  "display_rule": "prepared_9x16",
  "sequence": {
    "mode": "step_cut",
    "transition": "quick_cut"
  }
}
```

## 10. 显示规则与动效规则

### 10.1 渲染顺序

所有 clip 必须遵守固定顺序：

```text
source image
-> display_rule 生成 1080x1920 base frame
-> whole-frame motion
-> overlay/callout motion
-> subtitles
```

动画只能作用于已经排版好的整帧画布，不能反过来决定图片裁剪。

### 10.2 Display Rule 白名单

```text
prepared_9x16
portrait_full_width
landscape_full_width_center
grid_showcase
split_compare
```

#### `portrait_full_width`

```text
竖图左右铺满 1080 宽度
按比例缩放
不横向留边
不拉伸
如果高度超过 1920，只允许受控 vertical_pan
```

#### `landscape_full_width_center`

```text
横图左右铺满 1080 宽度
高度按比例缩放
上下居中
上下空白用纯色、品牌底色或模糊背景补齐
不裁主体
不拉伸
不局部放大
```

#### `prepared_9x16`

```text
素材已经是 1080x1920 或接近 9:16
直接按宽高适配画布
不再裁切修复
```

### 10.3 Motion 白名单

```text
hold
whole_frame_push_in
whole_frame_pull_out
slide_left
slide_right
slide_up
slide_down
fade
crossfade
quick_cut
vertical_pan_for_tall_image
grid_to_single
single_to_grid
```

### 10.4 Overlay Motion 白名单

```text
highlight_box
arrow_callout
pulse_ring
label_tag
```

### 10.5 禁止项

```text
crop_focus
zoom_to_area
random_pan
browser_camera_track
局部放大横图
把横图裁成竖图局部
根据 focus_region 临时裁图
用录屏画面做最终功能展示
```

## 11. 字幕时间与画面匹配

时间轴由语音和字幕决定，图片在字幕段内排布。

```text
script segment time：由 Minimax timing 决定
visual subclip time：在 segment start/end 内自动分配
```

规则：

- 字幕描述单个主体：使用单图。
- 字幕描述多行业、多场景、多风格：必须使用 `image_sequence` 或 `image_grid`。
- 一段字幕内可以切多张图，但字幕不跟每张图闪动。
- 每张图展示时长建议 `0.8s - 1.6s`。
- 重点图可展示 `1.8s - 3.0s`。
- 少于 `0.7s` 默认不可读。
- 如果素材数量不足，文案必须降级，不允许硬说“多场景”“多行业”。

## 12. 视频模板

### 12.1 单功能种草

适合：门头招牌、活动美陈、VI、LOGO、电商、海报。

```text
0-3s    结果图快切 hook
3-6s    网站主页 / 功能入口
6-9s    功能参数或生成按钮截图
9-18s   多行业 / 多场景结果图
18-24s  功能价值总结
24s+    CTA + 固定片尾
```

最低素材门槛：

```text
1 张入口/路径图
1 张功能参数图
3 张结果图
```

### 12.2 多功能合集

适合：文生图能力合集、广告人常用功能合集。

```text
0-3s    多功能结果快切
3-6s    网站主页
6-10s   功能入口集合
10-22s  每个功能 2-3 张结果图
22-26s  功能矩阵总结
26s+    CTA + 片尾
```

最低素材门槛：

```text
至少 3 个功能
每个功能至少 2 张结果图
至少 1 张网站入口图
```

### 12.3 行业垂类视频

适合：餐饮、零售、商场、文旅、企业等。

```text
0-3s    行业痛点
3-6s    适用功能入口
6-20s   同行业多模块结果图
20-26s  行业解决方案总结
26s+    CTA + 片尾
```

最低素材门槛：

```text
至少 1 个行业
至少 2 个功能模块或 5 张同行业结果图
```

## 13. QA 规则

### 13.1 素材 QA

必须检查：

```text
素材文件存在
图片可打开
分辨率达到最低阈值
asset_kind 正确
result_page_evidence 不被当作 result_image
gpt_9x16 素材未明显改写原内容
素材 claims 有真实依据
```

### 13.2 Project QA

必须检查：

```text
visual_track 时间不重叠或断裂
每个 clip 有可渲染素材
display_rule 在白名单
motion 在白名单
禁止局部放大类 motion
字幕提到多行业时 visual clip 至少有多张相关图
字幕提到某功能时画面素材 module 匹配
结果型文案必须绑定 result_image 或 case_image
```

### 13.3 Render QA

必须检查：

```text
无黑帧
字幕不遮挡主体
图片没有被局部裁坏
横图左右铺满、上下居中
竖图左右铺满
快切图可读
contact sheet 信息密度足够
```

## 14. 推荐重构步骤

### 阶段一：定 schema

- 定稿素材内存对象结构
- 定稿 `material_groups.json`
- 定稿 `video_project.schema_version=2`
- 定稿 display/motion 白名单

### 阶段二：重构 CDP 为素材采集器

- 移除标准链路里的录屏依赖。
- `cdp-capture` 支持 `recording.enabled=false`。
- 新增素材采集任务生成器。
- 输出 screenshots、results、receipts。

### 阶段三：素材注册与 GPT keyframe

- 新增素材包注册脚本。
- GPT image 批量生成 9:16 keyframe。

### 阶段四：升级视频 planner

- planner 从素材 group 选图。
- 根据视频类型选择模板。
- 根据字幕语义决定单图、快切、网格。
- 素材不足时自动降级文案。

### 阶段五：升级 FFmpeg 渲染器

- 支持 `image_sequence`。
- 支持 `grid_showcase`。
- 支持 slide/fade/quick_cut。
- 所有 motion 作用在 base frame 上。
- 移除录屏 camera track 逻辑。

### 阶段六：清理旧链路

- 移除 CDP recording 作为推荐路径的文档。
- 移除录屏注册脚本在主 README 的地位。
- 移除旧 demo case 复用建议。
- 删除或归档 Electron / CDP PoC 文档。

## 15. 最终标准

一条合格的视频必须满足：

```text
素材来源真实
素材分类清楚
画面信息量足
图片展示规则稳定
动画有节奏但不破坏主体
字幕和图片语义匹配
结果展示不是网页截图冒充
渲染过程不依赖现场浏览器状态
```

一句话总结：

```text
CDP 负责把真实网站能力变成素材，GPT image 负责把素材变成可入镜关键帧，Minimax 负责声音和字幕时间，FFmpeg 负责确定性动效合成。
```
