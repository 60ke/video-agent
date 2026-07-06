# Video Agent 架构精简与升级方案 (Pipeline V2)

## 1. 核心背景与目的
在先前的版本中，项目过度依赖复杂的无头浏览器渲染栈（HyperFrames / GSAP）和不可控的画面动效叠加，导致最终产出的视频“步子迈得太大”，不仅极不稳定，而且常常出现严重的图文不符、画面裁剪过度（局部盲人摸象）等现象。

**本次重构的核心哲学是：“降维求稳，退一步海阔天空”。**
放弃目前在工程上缺乏绝对控制力的“花哨动态视频生成”，回归到高度确定性的 **“高级动态 PPT”** 模式（静态图/截图 + 高质量语音 + 精准字幕 + 转场）。剥离外部冗余依赖，**只死磕“图、文、声”三者的准确性与对应关系**。

## 2. 核心修改与工作流演进

### 2.1 渲染引擎极简化 (HyperFrames -> FFmpeg)
*   **痛点**：HyperFrames 渲染链路重、容易报错、对运行环境依赖极强。
*   **方案**：新增 `scripts/render_simple_ffmpeg.py`。
*   **收益**：完全抛弃无头浏览器。使用原生的 FFmpeg `concat` 滤镜将关键帧图片直接串联，利用 `subtitles` 滤镜硬压制字幕。对不同尺寸的图片（如网站横屏和生成物竖屏）采用智能黑边填充（Letterbox）策略，彻底解决画面被不合理裁切的问题。速度极快，且零依赖。

### 2.2 音频与时间轴云端化 (本地 TTS + FunASR -> Minimax T2A)
*   **痛点**：以往流程需要先跑本地声音生成（或者调第三方），再去跑极其厚重的本地 FunASR 提取时间轴，速度慢、环境配置复杂，且二次对齐容易出错。
*   **方案**：新增 `scripts/generate_voice_minimax.py`，全量替换旧版 `generate_voice.py` 和 `run_funasr.py`。
*   **收益**：一步到位！通过调用 Minimax 的 T2A Http 接口，不仅直接获取高质量的官方音色（如 `male-qn-qingse`），还可以通过设置 `subtitle_enable: true`，直接在一次请求内拿到引擎原生的毫秒级字/句级时间戳。不仅让整个工程“变轻了”，速度更是提升了数十倍，画面卡点达到理论上的 100% 精确。

### 2.3 视觉前置规划 (Visual Planning)
*   **痛点**：以往大模型在写脚本时是“先想词，再找图”，导致经常出现“用网页界面的截图去解说生成效果”等逻辑错乱现象。
*   **方案**：在生成视频脚本前，强制要求大模型输出“视觉来源设计”。即必须先确定这张图的来源是 **“网页界面截图 (Website Screenshot)”** 还是 **“生成的最终结果图 (Generated Result)”**，定好画面骨架后，再为其填充配音文案。

### 2.4 视觉后置兜底 (Visual QA)
*   **痛点**：生成完毕后没有对图文逻辑进行机器校验，只能靠人工排雷。
*   **方案**：利用“高级 PPT 模式”每一帧停留时间长、总图量少（20秒视频仅需约10-15张图）的特性，直接提取 `contact_sheet.jpg`（关键帧拼图）。结合生成好的 `video_script.json`（剧情脚本），交给多模态视觉大模型（Vision LLM）进行低成本、极速的二次校验。校验“解说词”与“实际画面”是否逻辑一致。若校验失败，低成本重跑 FFmpeg 即可。

## 3. 全新极简流水线总览

1. **Material Gathering**: Kimi WebBridge 抓取网站实况、截图及生成结果（`image_resources.json`）。
2. **Visual Planning & Scripting**: 大模型先行决定图片来源与骨架，再填充旁白文案（`video_script.json`）。
3. **Voice & Subtitle Sync**: 运行 `generate_voice_minimax.py`，一键调用 Minimax 接口，秒级输出 `audio/voice.mp3` 与原生的 `output/minimax/minimax_alignment.json`。
4. **Project Assembly**: 构建 `video_project.json` 和 `subtitle_track.json`，把“声、文、图”精准锁定。
5. **Fast Rendering**: 运行 `render_simple_ffmpeg.py`，FFmpeg 读取时间轴和图片，秒级合成高级 PPT 视频。
6. **Vision QA**: 视觉模型抽查审片，通过后直接交付。

---
*文档更新时间：2026-07-06*
