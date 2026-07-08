# CDP 网站截图素材范围与流程定义

本文档定义 `kehuanxiongmao.com` 网站截图素材的固定结构。CDP 只负责打开页面、复用登录态、执行 hover/click/scroll、截取干净截图，并输出坐标元数据；红框、箭头、鼠标圆圈、点击脉冲等强调效果不直接烧进 CDP 原图，而是作为 `callouts` 元数据透传给 GPT image 或视频 overlay 轨道处理。

## 一、固定截图结构

每个站点只保留一张网站主页截图；每个功能模块保留一组“入口点击截图 + 参数面板截图”。所有网站截图素材直接扁平存放在 `assets/sites/`，不再为网站截图额外建立分类目录或 sidecar JSON 文件。

| 类型 | 数量 | 作用 | 推荐截图范围 |
| --- | --- | --- | --- |
| 网站主页截图 | 每站点 1 张 | 表达平台首页、侧边栏、文生图入口和案例资源库氛围 | 桌面视口全屏，滚动到顶部，包含左侧导航和首页主要卡片 |
| 功能路由点击截图 | 每功能 1 张 | 表达从首页/侧边栏进入该功能的点击路径 | 视口截图或左侧区域裁切，必须包含“文生图”入口、hover 菜单、目标功能项 |
| 功能参数截图 | 每功能 1 张为主 | 表达该功能需要填写什么参数、在哪里开始生成 | 功能页左侧 `.left-panel-wrap` 参数面板，包含标题、上传区、核心字段、开始生成按钮 |

如果某个功能的必填参数首屏无法完整展示，允许补充第二张参数截图，命名为 `参数补充_002`。默认标准仍是每功能一张参数截图。

## 二、文件命名

截图文件名采用中文优先，避免网站中文信息在英文映射中丢失。网站截图素材不写独立 JSON 信息，站点、模块、功能、截图类型直接从文件名解析。功能入口截图、参数面板截图是固定槽位，不加 `001`。只有结果图、案例图、同类多张展示图这类序列素材才加序号。

示例：

```text
assets/sites/柯幻熊猫_网站_主页_原始桌面截图.jpg
assets/sites/柯幻熊猫_文生图_活动美陈_功能入口截图.png
assets/sites/柯幻熊猫_文生图_活动美陈_参数面板截图.png
assets/sites/柯幻熊猫_文生图_图文广告_车贴_功能入口截图.png
assets/sites/柯幻熊猫_文生图_图文广告_车贴_参数面板截图.png
```

命名解析规则：

- `柯幻熊猫`：站点名
- `网站` / `文生图`：顶层素材类型或一级业务模块
- `图文广告`：文生图下的一级入口，路径上比普通文生图功能多一层
- `车贴`、`活动美陈`：最终功能项
- `功能入口截图`、`参数面板截图`、`原始桌面截图`：截图类型

CDP 运行时可以在内存中保留坐标、字段信息、callouts 等临时元数据，但采集完成后不为这些网站截图生成额外 JSON 文件。

当某个视频 case 需要使用这些网站截图时，再通过注册入口把筛选后的图片写入该 case 的上下文：

```powershell
python scripts\register_site_assets.py --case cases\<case_name> --feature 活动美陈 --json
python scripts\register_site_assets.py --case cases\<case_name> --feature 图文广告/车贴 --json
```

注册脚本会复制命中的截图到 `cases/<case_name>/assets/sites/`，并写入该 case 的 `asset_manifest.json` 和 `image_resources.json`。全局 `assets/sites/` 仍然只保存图片，不保存 sidecar JSON。

## 三、前端功能范围

当前前端路由中，`文生图`主功能位于 `/textToImage` 下。一级子功能共 18 个；其中 `图文广告`展开后有 15 个二级子功能。因此按最终可点击功能项统计为 `17 + 15 = 32` 个。

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
| 图文广告 | `/graphic-ad` | `views/graphic-ad/index` | 父级模块，展开后见子功能 |

### 3.1 图文广告二级子功能（15 个）

`图文广告`是文生图一级菜单中的特殊模块，hover 后会展开二级子菜单。它在 URL 和素材命名上多一个层级，但整体仍归属到 `文生图` 下面。当前可见 15 个子功能：

| 功能名称 | 路由 | 参数截图标题 |
| --- | --- | --- |
| 车贴 | `/graphic-ad/car-sticker` | `图文广告-车贴` |
| 贴纸 | `/graphic-ad/sticker` | `图文广告-贴纸` |
| 灯箱 | `/graphic-ad/light-box` | `图文广告-灯箱` |
| 菜单 | `/graphic-ad/menu` | `图文广告-菜单` |
| 展板 | `/graphic-ad/board` | `图文广告-展板` |
| 直播背景 | `/graphic-ad/live-background` | `图文广告-直播背景` |
| banner | `/graphic-ad/banner` | `图文广告-banner` |
| 朋友圈海报 | `/graphic-ad/moments-poster` | `图文广告-朋友圈海报` |
| 单页 | `/graphic-ad/flyer` | `图文广告-单页` |
| 台历 | `/graphic-ad/calendar` | `图文广告-台历` |
| 名片 | `/graphic-ad/business-card` | `图文广告-名片` |
| 高炮 | `/graphic-ad/billboard` | `图文广告-高炮` |
| 易拉宝/展架 | `/graphic-ad/rollup-banner` | `图文广告-易拉宝/展架` |
| 电梯广告 | `/graphic-ad/elevator-ad` | `图文广告-电梯广告` |
| 胸卡&工牌 | `/graphic-ad/badge` | `图文广告-胸卡&工牌` |

图文广告采集流程：hover `文生图` → 展开 hover 菜单 → hover `图文广告` → 展开子菜单 → 截取包含子菜单的入口截图 → 点击子功能项进入参数页 → 截取参数面板。素材命名采用 `柯幻熊猫_文生图_图文广告_子功能_截图类型.png`。

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
4. 采集完成，截图文件直接存入 `assets/sites/` 目录，不写 sidecar JSON。
5. 将干净截图 + callouts 交给 GPT image 生成 9:16 视频关键帧。
6. 视频生成阶段只消费由截图文件注册得到的 case 素材上下文，不再实时依赖网站截图。
