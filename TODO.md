# Video Agent TODO

本文只记录当前架构上尚未完成的工作。已落地设计和历史评审不在这里重复保存。

## P0：文案 API 稳定化

- 将 Story Planner 的 OpenAI-compatible 配置扩展为按阶段 Provider 路由。
- 为 AI Narration 增加结构化错误修复和有限重试，仍只输出统一 `Narration` 契约。
- 保证 API 生成文案与 `script_locked` 在 `speech` 阶段完全汇合。
- Manifest 记录 Provider、模型、Prompt 和契约版本，不记录 Key。

## P0：场景语义覆盖

- 扩充编辑、局部修改、高清导出、图片保存等网站功能场景，但继续复用 ActionScene 主链。
- 为更多“输入 -> 输出”业务建立显式 relationship kind，禁止文件名猜测因果关系。
- 对无法可靠分类的文案输出清晰诊断，并使用 `light_sweep_fallback`，不自动插入无关素材。

## P1：派生素材能力

- 将编辑流程的固定模板和焦点区域扩展为可配置模板族。
- 增加同图不同模块的 `grid_reveal` 派生与编排支持。
- 完善长图、超宽图、透明素材和动画媒体的方向策略。
- 继续复用内容哈希 registry，所有动态 Prompt 保存来源、模型和输出哈希。

## P1：Remotion 动效

- 扩充横屏、竖屏、长图分别适用的 CardStack、SlideGallery、GridReveal 参数。
- 把参数花字拆成稳定底图层与透明文字动画层，避免两张整图渐变造成尺寸跳变。
- 将编辑流程的放大镜、局部按钮命中和弹窗出现参数纳入场景配置。
- 保持每个 Effect 自己声明最短帧数和可读停留，不引入全局硬限制。

## P2：素材维护

- 为 `assets/relationships.json` 提供独立注册和检查 CLI。
- 为固定网站派生素材提供清单差异报告，源截图变化时只重做受影响项。
- 清理仍保留在契约中的历史质量状态命名，使“项目外人工确认”和“运行时机器完整性检查”语义更清楚。

## 暂不实施

- 项目内 AI 视觉审核或 Vision Critic。
- 浏览器录屏作为成片链路。
- 运行时基于 CDP 坐标绘制框选。
- V2 兼容层。
