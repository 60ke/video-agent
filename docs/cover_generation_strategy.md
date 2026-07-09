# Cover Generation Strategy

本文档定义短视频封面图的生成策略。封面图应基于：

- 前端传入的封面标题
- 当前视频的字幕内容 / 文案主题
- 当前视频已引用的参考图（结果图、网站截图、功能页截图等）

生成一张适合短视频平台使用的竖屏封面图。

## 1. 基本原则

推荐把封面图生成作为独立步骤接入，而不是混入视频渲染：

```text
video_project.json / subtitle_track / cover input
  -> build_cover_plan.py
  -> render_cover_image.py
  -> output/cover/cover_main.png
```

也可以使用一键包装脚本：

```text
render_with_cover.py
  -> build_cover_plan.py
  -> render_cover_image.py
```

其中：

- `build_cover_plan.py`：根据字幕内容、项目素材和前端入参生成 `cover_plan.json`
- `render_cover_image.py`：调用 GPT Image 生成最终封面图
- `render_with_cover.py`：串联封面规划和封面渲染，适合常规调用

## 2. 输入约定

建议上游提供：

```json
{
  "cover": {
    "title": "前端传入的封面标题",
    "subtitle_hint": "可选补充短句",
    "style_hint": "可选风格提示",
    "reference_asset_ids": ["asset_xxx", "asset_yyy"]
  }
}
```

### 强约束

`cover.title` 为必填，且必须严格使用原文：

```text
不允许改字
不允许漏字
不允许乱码
不允许同义替换
```

如果系统不能保证主标题正确，应标记为待审核，而不是输出错误标题。

## 3. 尺寸与安全区

推荐默认生成竖屏封面：

```text
1080 x 1920
```

必须满足平台裁剪约束：

```text
竖屏封面最终会被裁剪中央 3:4 区域
主标题、人物主体、产品主体、补充短句等核心信息必须集中在中央安全区
3:4 安全区之外只能做背景延展、描边、光效、渐变和装饰，不能放关键信息
```

对 `1080 x 1920` 画布，可近似理解为：

```text
中央安全区：1080 x 1440
上下各约 240px 为非关键区域
```

因此：

- 主标题必须在中央安全区内
- 主体人物 / 主体产品 / 结果图主体必须在中央安全区内
- 补充短句必须在中央安全区内
- 安全区外不放关键文案

## 4. 素材选择策略

封面不应堆太多图，建议只使用 1~3 张最有效的参考图。

优先级：

1. **结果图 / 效果图优先**：如果视频主题是“某功能能生成什么效果”，结果图应成为封面主体。
2. **关键 UI 截图次优先**：可辅助说明“这是某网站功能”，但不能抢占主视觉。
3. **首页 / 流程页谨慎使用**：更适合作为视频过程素材，不宜做封面主体。

没有显式 `reference_asset_ids` 时，可自动选：

```text
1. 与当前视频主题最相关的 result asset
2. 当前视频中最关键、出现频率高的结果图
3. 与字幕主题最匹配的单张功能截图
```

## 5. 文案提炼策略

封面图文字建议分两层：

### A. 主标题

直接使用：

```text
cover.title
```

必须逐字一致。

### B. 补充短句

可由前端提供，也可从字幕中提炼。建议：短、明确、高信息密度、偏结果导向 / 卖点导向。

例如：

```text
一键生成品牌视觉
30 秒看懂功能亮点
上传描述就能出图
```

## 6. 视觉构图建议

推荐三类封面构图：

### 类型 A：结果图主视觉 + 主标题

适用于 logo 生成、品牌设计、海报生成、包装设计等。

```text
中央主体：结果图 / 设计成品
上中区域：主标题
下中区域：补充短句
外围：背景延展、渐变、描边、光效
```

### 类型 B：结果图主体 + 小面积 UI 提示

适用于网站功能种草、功能介绍。

```text
中央主体：结果图
一侧或下侧：小比例 UI 卡片 / 网站功能页
上中区域：主标题
下中区域：补充短句
```

### 类型 C：人物 / 产品主体 + 结果卡片

适用于人物或商品导向内容，但主体仍必须落在中央安全区内。

## 7. GPT Image 提示词要求

封面图应走独立 GPT Image 任务，不用程序最终拼图。

Prompt 必须包含这些硬约束：

```text
1. 生成竖屏短视频封面图
2. 主标题必须严格渲染为 cover.title 原文，不能改字、漏字、乱码
3. 所有核心内容必须集中在中央 3:4 安全区
4. 安全区外只能做背景延展与装饰，不能放关键信息
5. 参考图仅用于主体内容、结果展示和风格参考，不得引入无关事实
```

## 8. 新增脚本

### `scripts/build_cover_plan.py`

职责：

```text
读取 video_project.json / video_script.json / subtitle_track
读取 cover.title / subtitle_hint / style_hint / reference_asset_ids
挑选 1~3 张参考图
生成 cover_plan.json
```

默认输出：

```text
output/cover/cover_plan.json
output/reports/cover_plan_report.json
```

### `scripts/render_cover_image.py`

职责：

```text
读取 cover_plan.json
生成 reference sheet
调用 GPT Image 生成封面图
输出 cover_main.png
```

默认输出：

```text
output/cover/cover_reference_sheet.png
output/cover/cover_main.png
output/cover/cover_main_3x4_crop_preview.png
output/reports/cover_generation_report.json
```

`cover_main_3x4_crop_preview.png` 用于人工快速检查裁剪后的中央安全区效果。

### `scripts/render_with_cover.py`

职责：

```text
一条命令完成 cover_plan 构建和 cover image 渲染
```

适合前端/后端在已有 `video_project.json` 或 `video_project.effects.json` 后直接调用。

## 9. QA 建议

至少检查：

```text
[ ] 主标题与前端传入标题完全一致
[ ] 结果图 / 主体人物 / 主体产品位于中央 3:4 安全区
[ ] 补充短句位于中央安全区
[ ] 安全区外没有关键信息
[ ] 无乱码、无错误文案
[ ] 参考图主体被正确使用，无无关新增内容
```

推荐增加 OCR 校验：

```text
OCR 提取封面主标题
与 cover.title 做逐字对比
不一致则标记 review_required
```

## 10. 命令示例

一键生成：

```bash
python scripts/render_with_cover.py \
  --case cases/<case> \
  --project cases/<case>/video_project.effects.json \
  --title "封面主标题" \
  --config config/gpt_image.local.json \
  --json
```

分步执行：

```bash
python scripts/build_cover_plan.py \
  --case cases/<case> \
  --project cases/<case>/video_project.effects.json \
  --title "封面主标题" \
  --json

python scripts/render_cover_image.py \
  --case cases/<case> \
  --config config/gpt_image.local.json \
  --json
```

本地 dry-run 不调用 GPT Image：

```bash
python scripts/render_with_cover.py \
  --case cases/<case> \
  --project cases/<case>/video_project.effects.json \
  --title "封面主标题" \
  --dry-run \
  --json
```
