# CDP Capture

`cdp-capture` is now a website screenshot material capture tool. It keeps Chrome login/profile support and captures clean website states plus callout metadata. It does not record browser videos and does not encode MP4 assets for the video pipeline.

## Install

```powershell
cd cdp-capture
npm install
```

## Login Profile

Use a visible Chrome window to log in and export `auth_state.json`:

```powershell
node bin/cdp-capture.js profile login kehuanxiongmao --url https://www.kehuanxiongmao.com
```

- The fixed profile directory is `profiles/kehuanxiongmao/`.
- After manual login, return to the terminal and press Enter.
- Cookies, localStorage, and sessionStorage are saved for later screenshot capture.

## Capture Website Materials

Capture homepage, feature-entry, and parameter-panel screenshots:

```powershell
node bin/cdp-capture.js capture-material activity_meichen --mode visible
node bin/cdp-capture.js capture-material "*" --mode headless
```

Useful options:

```powershell
node bin/cdp-capture.js capture-material graphic_ad --children car_sticker,lightbox --mode visible
node bin/cdp-capture.js capture-material vi --output ..\assets\sites --callouts ..\assets\sites\_callouts.json
```

The output filenames follow the site material naming policy, for example:

```text
柯幻熊猫_文生图_文化墙_功能入口截图.png
柯幻熊猫_文生图_文化墙_参数面板截图.png
柯幻熊猫_文生图_图文广告_车贴_参数面板截图.png
```

`_callouts.json` stores target boxes and semantic hints. The V3 deterministic renderer uses those hints to crop the relevant panel and align highlight/click effects to word-level cues. Website UI is not redrawn by GPT Image.

## Capture Contract

- CDP captures clean screenshots and structured coordinates only.
- Do not bake cursor effects, click rings, or red boxes into raw screenshots.
- Use the fixed `kehuanxiongmao` profile for 柯幻熊猫.
- If a generation workflow is requested and the saved profile is not logged in, refuse capture instead of running an anonymous flow.
- For 文生图 modules, use `references/site_profiles/kehuanxiongmao_text_to_image_modules.json` as the source of truth for route, label, and page title.
- For `图文广告`, include the extra child layer in the filename path: `柯幻熊猫_文生图_图文广告_<子功能>_<截图类型>.png`.
- Parameter screenshots may fall back to the full page if a precise panel crop is unstable; GPT image can repair the 9:16 layout later.

## Result Authenticity

Generated result images are not captured through this screenshot-only tool unless an explicit generation workflow is implemented for the current module. Final result visuals must be saved or exported under `assets/results/` and registered by rebuilding `assets/catalog.json`.

Avoid false positives:

- Do not treat logos, sample images, empty states, loading placeholders, or old gallery results as current generated results.
- When a live generation workflow is used, every required input must be filled and the real `开始生成` action must be executed after login verification.
- Result images shown in a final video must be tied to the current case receipt when the video claims a fresh website generation.

## CLI

```text
cdp-capture profile login <profile-id> [options]
cdp-capture capture-material <module-id|*> [options]
```

Profile options:

```text
--url <url>       URL to open
--port <port>     CDP port
--width <px>      Window width
--height <px>     Window height
```

Capture options:

```text
--profile <id>    Chrome profile id
--port <port>     CDP port
--mode <mode>     headless or visible
--width <px>      Viewport width
--height <px>     Viewport height
--output <dir>    Assets output directory
--callouts <file> Callout registry path
--no-homepage     Skip homepage capture
--no-entry        Skip feature entry capture
--no-params       Skip feature params capture
--children <ids>  Comma-separated child ids
```

## Architecture

```text
cdp-capture/
├─ bin/
│  └─ cdp-capture.js       CLI entry
├─ lib/
│  ├─ cdp-client.js        CDP WebSocket client
│  ├─ chrome-launcher.js   Chrome launcher
│  ├─ events.js            NDJSON-style event helper
│  ├─ form-inspector.js    Required-form inspection script
│  ├─ material-capture.js  Screenshot material capture workflow
│  ├─ profile-auth.js      Login/profile state management
│  └─ utils.js             Shared helpers
└─ profiles/               Runtime Chrome profiles
```
