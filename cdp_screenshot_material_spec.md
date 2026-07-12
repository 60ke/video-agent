# CDP 网站截图素材规范（V3）

CDP 只负责复用登录态、导航、等待稳定页面、截取干净截图和输出 DOM 坐标。它不录制视频、不在原图烧入红框，也不负责成片构图。

## 固定素材

- 每站点一张主页：`柯幻熊猫_网站_主页_原始桌面截图.jpg`
- 每功能一张入口：`柯幻熊猫_文生图_<功能>_功能入口截图.png`
- 每功能一张参数页：`柯幻熊猫_文生图_<功能>_参数面板截图.png`
- 图文广告保留三级路径：`柯幻熊猫_文生图_图文广告_<子功能>_<截图类型>.png`

功能截图不加 `001`。只有同类多张结果图使用顺序号。

## 稳定截图流程

1. 验证已登录；需要生成或登录态素材时，未登录立即拒绝。
2. 等待目标路由、标题、核心面板和字体加载完成。
3. 等待布局连续多次采样稳定，关闭 toast、弹窗和下拉残影。
4. 入口图保持 hover 菜单打开，参数图保持所有临时菜单关闭。
5. 截图后再次读取目标 DOM，确认目标仍可见且坐标未漂移。
6. 将 target box、可选 panel box、标签、角色和意图写入 `assets/sites/_callouts.json`。

参数页精确面板裁切失败时允许保存完整页面。V3 渲染器会使用 callout 在 9:16 安全舞台内做确定性重构，不修改 UI 像素。

## Callout

```json
{
  "target_label": "品牌名称",
  "target_role": "required_form_field",
  "intent": "required_field",
  "box": {"x": 0.1, "y": 0.3, "w": 0.7, "h": 0.08},
  "panel_box": {"x": 0.04, "y": 0.18, "w": 0.92, "h": 0.62}
}
```

坐标均为原图归一化坐标。`box` 表示语义命中目标，`panel_box` 表示构图时应保留的上下文。入口页优先提供菜单 panel；参数页优先提供整组字段 panel。

## 注册

截图直接写入 `assets/sites/`，然后执行：

```powershell
python -m video_agent catalog --assets assets --json
```

V3 case 从全局 catalog 按中文语义路径生成运行快照，不再复制素材或维护 `image_resources.json`、`asset_manifest.json`。
