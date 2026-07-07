# Video Agent 架构精简与升级方案 (Pipeline V2)

## 1. 核心背景与目的
在先前的版本中，项目过度依赖复杂的无头浏览器渲染栈（HyperFrames / GSAP）和不可控的画面动效叠加，导致最终产出的视频“步子迈得太大”，不仅极不稳定，而且常常出现严重的图文不符、画面裁剪过度（局部盲人摸象）等现象。

**本次重构的核心哲学是：“降维求稳，退一步海阔天空”。**
放弃目前在工程上缺乏绝对控制力的“花哨动态视频生成”，回归到高度确定性的 **“高级动态 PPT”** 模式（静态图/截图 + 高质量语音 + 精准字幕 + 转场）。剥离外部冗余依赖，**只死磕“图、文、声”三者的准确性与对应关系**。

## 2. 核心修改与工作流演进

### 2.1 渲染引擎极简化 (HyperFrames -> FFmpeg)
*   **痛点**：HyperFrames 渲染链路重、容易报错、对运行环境依赖极强。
*   **方案**：新增 `scripts/render_simple_ffmpeg.py`。
*   **收益**：完全抛弃无头浏览器。渲染器用 Pillow 合成受控关键帧并通过 FFmpeg `rawvideo` 管道编码，最后用 ASS 滤镜硬压制字幕。对不同尺寸的图片采用统一画布与白名单运动策略，避免不可控局部裁切。

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

1. **Material Gathering**: CDP 抓取网站实况、截图及生成结果（`image_resources.json`）。需要展示真实操作路径时，使用 CDP 录制一段短的横屏操作素材，并通过 `scripts/register_cdp_recording.py` 注册为 `assets/recordings/` 资产。
2. **Visual Planning & Scripting**: 大模型先行决定图片来源与骨架，再填充旁白文案（`video_script.json`）。
3. **Voice & Subtitle Sync**: 运行 `generate_voice_minimax.py`，一键调用 Minimax 接口，秒级输出 `audio/voice.mp3` 与原生的 `output/minimax/minimax_alignment.json`。
4. **Project Assembly**: 构建 `video_project.json` 和 `subtitle_track.json`，把“声、文、图”精准锁定。
5. **Fast Rendering**: 运行 `render_simple_ffmpeg.py`，按 `visual_track` 合并视觉组、应用受控整帧运动，并用 FFmpeg 合成视频。
6. **Vision QA**: 视觉模型抽查审片，通过后直接交付。

---

## 4. 受控运动升级（Controlled Motion, 2026-07-07）

**背景**：纯静止的“高级 PPT”验证了图文声的准确性，但画面表现力不足，短视频观感偏死板。这次升级只解决“动起来”，不重新引入旧版 HyperFrames 那种不可控的花哨动效。

**核心原则不变**：`video_project.json` 仍是唯一权威，渲染器仍是哑执行器；运动效果只能从白名单里选，参数有硬性上限，禁止任何逐案例即兴发挥。

### 4.1 `visual_track` 新增字段

每个事件可以携带：

```json
"motion": { "name": "push_in", "amount": 0.028, "anchor": "center" },
"transition_in": { "name": "crossfade", "duration": 0.22 }
```

`motion.name` 白名单（`scripts/validate_video_project.py` 强制校验）：

- `hold`：完全静止（默认，密集/多图 UI 布局必须用这个，保证可读性）。
- `push_in` / `pull_out`：整帧、锚点固定在画布中心的缓慢缩放，`amount` 上限 `0.06`（建议 `0.025-0.04`）。绝不是局部裁剪或任意方向的放大，视觉上是均匀缩放整个合成画布后居中裁回原尺寸。

`transition_in.name` 白名单：

- `cut`：硬切（默认）。
- `crossfade`：`duration` 0-0.6s 之间的交叉淡入淡出，仅在画面（`layout` + `asset_ids`）真正发生变化时才允许使用。

### 4.1.1 浏览器录屏布局

CDP 操作录屏使用 `layout=browser-recording-fit-width`。录屏保持正常横屏浏览器尺寸，渲染时按 1080px 宽度等比缩放并在 1080x1920 画布内上下居中，不裁切、不做额外 push-in。录屏只展示进入功能、真实填写必填参数、点击 `开始生成` 的动作；点击生成 action 上设置 `stopRecordingAfter: true` 后停止录屏。注意这不是自动化任务结束点：同一个 CDP task 必须继续等待/获取真实生成结果，并把结果保存到 `assets/results/`，最终结果展示仍使用这些真实结果图。

### 4.2 防闪屏是结构性强制，不是靠人工审片

`scripts/validate_video_project.py` 新增不变量：如果相邻两个 `visual_track` 事件的 `layout + asset_ids` 完全相同（比如同一张图配了两句字幕），渲染器会把它们合并成一段连续镜头，运动只跑一次、不重启。因此校验器强制要求：

- 这类相邻同视觉事件之间不能声明 `crossfade`（只能 `cut` 或省略），否则报错。
- 这类事件的 `motion.name` / `amount` 必须完全一致，否则报错（避免合并后缩放突然跳变）。

`scripts/build_video_project.py` 现在按这个规则自动生成默认值：密集 UI / 多图网格布局默认 `hold`；单主体截图/结果图默认小幅 `push_in`；只有当视觉真正切换时才给 `crossfade`，同视觉延续始终是 `cut`。

### 4.3 渲染器实现（`scripts/render_simple_ffmpeg.py`）

不引入 MoviePy 或无头浏览器。渲染器把合并后的“视觉组”逐帧合成为 RGB 裸帧，通过 `stdin` 管道流式喂给一个 FFmpeg 进程（`-f rawvideo`），FFmpeg 用 `ass` 滤镜一次性烧录字幕并编码输出。相比旧版 concat 静止帧拼接：

- 运动是逐帧计算的连续曲线（`smoothstep` 缓动），不是整数像素跳变，杜绝抖动。
- 每张基础合成图只解码/拼版一次并缓存，逐帧只做整帧缩放+居中裁剪，性能可控。
- FFmpeg 的 stdout/stderr 重定向到日志文件而不是管道，避免大量日志把 stdin 写入阻塞死锁。

### 4.4 验收方式

用合成测试用例验证过：`hold` 保持像素级静止；`push_in`/`pull_out` 的缩放边界均匀且单调，无局部裁剪；`crossfade` 只在真实切换视觉时出现且时长可控；同视觉合并后运动连续无跳变。`scripts/make_contact_sheet.py` 和 `scripts/render_qa.py` 无需改动即可直接用于新渲染器的输出。

---
*文档更新时间：2026-07-07*
