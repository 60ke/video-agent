# CDP 网站截图素材范围与流程定义

本文档定义 `kehuanxiongmao.com` 网站截图素材的固定结构。CDP 只负责打开页面、复用登录态、执行 hover/click/scroll、截取干净截图，并输出坐标元数据；红框、箭头、鼠标圆圈、点击脉冲等强调效果不直接烧进 CDP 原图，而是作为 `callouts` 元数据透传给 GPT image 或视频 overlay 轨道处理。

## 一、固定截图结构

每个站点只保留一张网站主页截图；每个功能模块保留一组“入口点击截图 + 参数面板截图”。

| 类型 | 数量 | 作用 | 推荐截图范围 |
| --- | --- | --- | --- |
| 网站主页截图 | 每站点 1 张 | 表达平台首页、侧边栏、文生图入口和案例资源库氛围 | 桌面视口全屏，滚动到顶部，包含左侧导航和首页主要卡片 |
| 功能路由点击截图 | 每功能 1 张 | 表达从首页/侧边栏进入该功能的点击路径 | 视口截图或左侧区域裁切，必须包含“文生图”入口、hover 菜单、目标功能项 |
| 功能参数截图 | 每功能 1 张为主 | 表达该功能需要填写什么参数、在哪里开始生成 | 功能页左侧 `.left-panel-wrap` 参数面板，包含标题、上传区、核心字段、开始生成按钮 |

如果某个功能的必填参数首屏无法完整展示，允许补充第二张参数截图，命名为 `参数补充_002`。默认标准仍是每功能一张参数截图。

## 二、文件命名

截图文件名采用中文优先，避免网站中文信息在英文映射中丢失；程序侧稳定引用使用 `asset_id`。功能入口截图、参数面板截图是固定槽位，不加 `001`。只有结果图、案例图、同类多张展示图这类序列素材才加序号。

示例：

```text
柯幻熊猫_网站_主页_001_原始桌面截图.png
柯幻熊猫_文生图_活动美陈_功能入口截图.png
柯幻熊猫_文生图_活动美陈_参数面板截图.png
```

Manifest 中同时保存中文文件名和稳定 ID：

```json
{
  "asset_id": "site_flow.text_to_image.activity_decoration.params.001",
  "filename": "柯幻熊猫_文生图_活动美陈_参数面板截图.png",
  "site_label": "柯幻熊猫",
  "module_label": "文生图",
  "feature_label": "活动美陈",
  "capture_type": "参数面板截图"
}
```

## 三、前端功能范围

当前前端路由中，`文生图`主功能位于 `/textToImage` 下。一级功能模块如下：

| 功能名称 | 路由 | 页面组件 | 参数截图标题 |
| --- | --- | --- | --- |
| 门头招牌 | `/textToImage/signboard` | `views/textToSvg/index` | `门头招牌` |
| 文化墙 | `/textToImage/culture-wall` | `views/cultureWall/index` | 以页面实际 `.label-active` 为准 |
| 景观小品 | `/textToImage/landscape-sketch` | `views/landscapeSketch/index` | 以页面实际 `.label-active` 为准 |
| 美陈 | `/textToImage/visual-merchandising` | `views/visualMerchandising/index` | 以页面实际 `.label-active` 为准 |
| 活动美陈 | `/textToImage/activity-decoration` | `views/activityDecoration/index` | `文生图-活动美陈` |
| 会议美陈 | `/textToImage/meeting-decoration` | `views/meetingDecoration/index` | 以页面实际 `.label-active` 为准 |
| 旅游海报 | `/textToImage/travel-poster` | `views/travelProduct/index` | 以页面实际 `.label-active` 为准 |
| 婚礼美陈 | `/textToImage/wedding-decoration` | `views/weddingDecoration/index` | 以页面实际 `.label-active` 为准 |
| IP形象 | `/textToImage/ip` | `views/textToImageIp/index` | 以页面实际 `.label-active` 为准 |
| LOGO | `/textToImage/logo` | `views/textToImageLogo/index` | 以页面实际 `.label-active` 为准 |
| 电商 | `/textToImage/ecommerce` | `views/textToImageEcommerce/index` | `文生图-电商` |
| 展台 | `/textToImage/exhibit-booth` | `views/exhibitBooth/index` | 以页面实际 `.label-active` 为准 |
| 包装 | `/textToImage/packaging` | `views/packagingDesign/index` | 以页面实际 `.label-active` 为准 |
| 标识标牌 | `/textToImage/signage` | `views/signage/index` | 以页面实际 `.label-active` 为准 |
| VI | `/textToImage/vi-design` | `views/viDesign/index` | 以页面实际 `.label-active` 为准 |
| 海报 | `/textToImage/poster` | `views/textToImagePoster/index` | 以页面实际 `.label-active` 为准 |
| 活动物料 | `/textToImage/main-kv` | `views/textToImageMainKV/index` | 以页面实际 `.label-active` 为准 |

`图文广告`是 hover 菜单里的二级入口，属于 `/graphic-ad/*` 隐藏路由，可作为第二阶段单独扩展。它需要额外捕获父菜单项和子菜单项，不混入第一阶段文生图主链路。

## 四、各类截图的精确流程

### 1. 网站主页截图

目标：只截一次，作为站点级素材。

流程：

1. 打开首页 `/`。
2. 验证处于已登录状态；如果未登录，直接拒绝执行素材采集。
3. 滚动到顶部。
4. 等待首页功能卡片和案例资源库区域加载完成。
5. 截取桌面视口全屏，保留左侧导航、`文生图`卡片、操作指南/市场合作/案例资源库的顶部信息。

推荐元数据：

```json
{
  "capture_type": "网站主页截图",
  "route": "/",
  "viewport": "1920x1080",
  "callouts": [
    { "target_text": "文生图", "intent": "highlight_module_entry" },
    { "target_text": "案例资源库", "intent": "highlight_resource_library" }
  ]
}
```

### 2. 功能路由点击截图

目标：表达“文生图 -> 具体功能”的进入路径。

流程：

1. 从首页或任意已登录页面开始。
2. hover 左侧导航 `文生图`，等待 `.hover-submenu-panel` 展开。
3. 找到目标功能项，例如 `活动美陈`。
4. 截图前不点击目标项，保留菜单展开状态。
5. 输出目标项 DOM 坐标，作为后续 GPT image 红框或 overlay 鼠标点击的依据。

推荐截图范围：

- 普通模块：截取左侧导航 + hover 菜单 + 背后的首页功能卡片局部。
- `图文广告`二级模块：截取左侧导航 + 主 hover 菜单 + 子菜单面板。

推荐元数据：

```json
{
  "capture_type": "功能入口截图",
  "route": "/",
  "module_label": "文生图",
  "feature_label": "活动美陈",
  "selectors": {
    "trigger": ".hover-submenu-trigger",
    "panel": ".hover-submenu-panel",
    "item_text": "活动美陈"
  },
  "callouts": [
    { "target_text": "文生图", "intent": "hover_entry" },
    { "target_text": "活动美陈", "intent": "click_target" }
  ]
}
```

### 3. 功能参数截图

目标：表达进入功能后左侧参数面板的结构。

流程：

1. 点击功能入口，等待路由跳转到目标路径。
2. 等待 `.text-to-image-page .left-panel-wrap` 出现。
3. 滚动 `.content-box` 到顶部。
4. 关闭所有下拉框、弹窗、toast。
5. 截取 `.left-panel-wrap`，优先包含顶部标题、上传区、主要字段、补充描述、图片质量和底部 `开始生成`。
6. 输出字段列表、必填项、按钮坐标，用于后续视频讲解和 GPT image 排版优化。

推荐元数据：

```json
{
  "capture_type": "参数面板截图",
  "route": "/textToImage/activity-decoration",
  "feature_label": "活动美陈",
  "selectors": {
    "panel": ".left-panel-wrap",
    "title": ".label-active",
    "scroll_container": ".content-box",
    "submit_button": ".el-action-btn"
  },
  "callouts": [
    { "target_text": "活动名称", "intent": "required_field" },
    { "target_text": "活动类型", "intent": "required_field" },
    { "target_text": "场景选择", "intent": "required_field" },
    { "target_text": "开始生成", "intent": "submit_action" }
  ]
}
```

## 五、已确认的关键参数范围

### 门头招牌

参数截图需要覆盖：

- 上传区：`实景图(可选)`、`参考图(可选)`
- 必填输入：`招牌名称`
- 门头属性：`行业*`、`场景`、`背景底板`、`字体材质`、`经营定位*`
- 补充信息：`补充描述`
- 生成动作：`开始生成`

注意：`办公楼前厅门头`、`工地门头`属于特殊行业，会影响部分联动字段展示。标准参数截图使用默认空态，不主动选择特殊行业。

### 活动美陈

参数截图需要覆盖：

- 上传区：`LOGO(可选)`、`参考图/KV(可选)`
- 必填输入：`活动名称`、`活动主题`
- 活动属性：`活动类型*`、`活动调性`、`视觉风格`、`场景选择*`、`空间类型*`
- 补充信息：`补充描述`
- 图片质量：`普通`、`高清`
- 生成动作：`开始生成`

标准空态中，`空间类型`默认是 `室内`。

### 电商

参数截图需要覆盖：

- 上传区：`商品图`、`产品规格参数图`、`参考图`
- 基础属性：`平台`、`国家`、`语言`
- 必填输入：`产品名称`、`产品品类`
- 类型选择：`1:1主图`、`商品详情页`
- 补充信息：`商品描述`
- 图片质量：`普通`、`高清`
- 生成动作：`开始生成`

注意：`商品详情页`会额外展示比例字段。标准参数截图先使用默认主图状态；如果后续要覆盖详情页视频样式，可补充 `电商_商品详情页_参数补充_002`。

## 六、GPT image 与视频轨道分工

CDP 原图保持干净，不直接画红框。后续分两类处理：

| 效果 | 处理位置 | 原因 |
| --- | --- | --- |
| 静态红框、箭头、文字标签 | GPT image | 可同时完成 9:16 排版和强调区域美化 |
| 鼠标圆圈、点击脉冲、光标移动 | 视频 overlay 轨道 | 需要和字幕/旁白时间精确同步 |
| 截图比例适配、留白、左右铺满 | GPT image | 生成可直接放入视频的高质量关键帧 |
| 轻微推入、平移、淡入淡出 | 视频 motion 轨道 | 保证同一素材可复用到多种视频样式 |

## 七、推荐执行顺序

1. 读取前端路由表，生成模块注册表。
2. 登录态检测，通过后采集唯一的网站主页截图。
3. 遍历文生图主模块：
   - hover `文生图`并采集功能入口截图；
   - 点击目标功能并采集参数面板截图；
   - 从 DOM 中提取标题、字段、必填项、按钮坐标。
4. 写入截图 manifest。
5. 将干净截图 + callouts 交给 GPT image 生成 9:16 视频关键帧。
6. 视频生成阶段只消费素材 manifest，不再实时依赖网站截图。
