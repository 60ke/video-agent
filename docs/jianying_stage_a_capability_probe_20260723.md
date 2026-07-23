# 剪映 Stage A 能力探针报告

状态：已完成  
日期：2026-07-23

## 1. 探针目标

本阶段只确认本机剪映与 `jianying-editor-skill` 的确定性能力边界，不进入
业务素材匹配、CDP 录制和生产链路切换。

## 2. 环境

| 项目 | 结果 |
|---|---|
| Skill 路径 | `C:/Users/CNGG/Desktop/jianying-editor-skill` |
| 剪映程序 | `C:/Users/CNGG/AppData/Local/JianyingPro/Apps/JianyingPro.exe` |
| 当前版本 | `11.1.0.14287` |
| 画布目标 | `1080x1920` |
| 帧率目标 | `30fps` |
| FFmpeg / FFprobe | 可用 |

## 3. 能力矩阵

| 能力 | 状态 | 结论 |
|---|---|---|
| 创建竖屏草稿 | 通过 | `JyProject` 可创建指定宽高的独立草稿 |
| 保存草稿 | 通过 | 已生成 `Diagnostic_Test` 并写入剪映草稿目录 |
| 导入图片和视频 | 通过 | `add_media_safe` 支持本地媒体与目标时间范围 |
| 导入配音和音效 | 通过 | `add_audio_safe` 支持独立音轨和目标时间范围 |
| 精确字幕片段 | 通过 | `add_text_simple` / `add_rich_text` 支持微秒时间范围 |
| 画面关键帧 | 通过 | 支持缩放、位置、旋转和透明度关键帧 |
| 鼠标事件录制 | 可用 | Recorder 可保存点击、移动、按键事件 JSON |
| 智能推近 | 有限可用 | 现有 `smart_zoomer.py` 使用固定节奏，不直接用于词级卡点 |
| 自动导出 | 不兼容 | 自动导出控制器只支持剪映 6 及以下；本机为 11.1 |

## 4. 已验证产物

诊断草稿：

```text
C:/Users/CNGG/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft/Diagnostic_Test
```

探针命令：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
python C:/Users/CNGG/Desktop/jianying-editor-skill/scripts/api_validator.py --json
```

首次执行仅因 Windows 默认 GBK 无法输出 Unicode 符号而失败；设置
`PYTHONIOENCODING=utf-8` 后完整通过。这是终端编码问题，不是草稿能力失败。

## 5. Stage B 约束

Stage B 只能通过结构化 `EditBlueprint` 调用上述能力：

- 帧号统一按 `30fps` 转为微秒，不在 Adapter 内重新估时；
- 画面、字幕、配音和 SFX 复用 `CompiledVideoTimeline` 的既有区间；
- 基础动效映射为关键帧，不调用固定时长的 `smart_zoomer.py`；
- 草稿生成成功与自动导出成功分开报告；
- 自动导出失败时保留可打开、可继续编辑的剪映草稿，不伪造 MP4 成功。

## 6. 结论

剪映 Skill 已具备 Stage B 所需的草稿执行能力。当前唯一未关闭的环境风险是
剪映 11.1 的自动导出兼容性；它不阻塞 `EditBlueprint -> 剪映草稿` 最小闭环，
但阻塞“无人值守导出 MP4”的生产验收。
