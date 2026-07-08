# Agent Notes

## CDP web recording direction

- The previous Electron MVP implementation is paused/abandoned for now because its recording quality and behavior were not satisfactory.
- Do not continue optimizing the Electron `openbridge-desktop` capturePage-based recorder unless explicitly requested.
- New quick validations should live in a separate CDP-focused subdirectory and use an external Chromium/Chrome process controlled through Chrome DevTools Protocol.
- The target validation path is:
  1. launch Chrome with `--remote-debugging-port`
  2. connect through CDP
  3. navigate to the target URL
  4. perform page actions through CDP
  5. capture frames with `Page.startScreencast`
  6. encode frames with FFmpeg
  7. output a small artifact package for manual review

