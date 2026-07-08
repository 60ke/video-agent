const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');

const WebSocket = require('../openbridge-desktop/node_modules/ws');
const ffmpegStatic = require('../openbridge-desktop/node_modules/ffmpeg-static');

const ROOT = __dirname;
const TARGET_URL = 'https://www.kehuanxiongmao.com';
const FPS = readPositiveIntEnv('CDP_FPS', 30);
const WIDTH = readPositiveIntEnv('CDP_WIDTH', 1280);
const HEIGHT = readPositiveIntEnv('CDP_HEIGHT', 720);
const QUALITY = readPositiveIntEnv('CDP_JPEG_QUALITY', 82);
const PORT = readPositiveIntEnv('CDP_PORT', 9333);
const PROFILE_ID = process.env.CDP_PROFILE_ID || 'kehuanxiongmao';
const now = new Date();
const TASK_ID = `task-${now.toISOString().replace(/[:.]/g, '-').replace('T', '_').slice(0, 23)}`;
const OUT_DIR = path.join(ROOT, 'output', TASK_ID);
const FRAMES_DIR = path.join(OUT_DIR, 'frames');
const CFR_DIR = path.join(OUT_DIR, 'cfr_frames');
const PROFILE_DIR = path.join(ROOT, 'profiles', PROFILE_ID);
const AUTH_STATE_PATH = path.join(PROFILE_DIR, 'auth_state.json');
const LOG_PATH = path.join(OUT_DIR, 'cdp.log');
const VIDEO_PATH = path.join(OUT_DIR, 'video.mp4');

function readPositiveIntEnv(name, fallback) {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_PATH, line, 'utf8');
}

function requestJson(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        body += chunk;
      });
      res.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch (err) {
          reject(err);
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(1500, () => {
      req.destroy(new Error(`Timeout requesting ${url}`));
    });
  });
}

async function waitForChrome(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      return await requestJson(`http://127.0.0.1:${port}/json/version`);
    } catch (err) {
      lastError = err;
      await sleep(250);
    }
  }
  throw lastError || new Error('Chrome did not expose CDP in time');
}

async function getPageWebSocketUrl(port) {
  const targets = await requestJson(`http://127.0.0.1:${port}/json/list`);
  const page = targets.find((target) => target.type === 'page');
  if (!page || !page.webSocketDebuggerUrl) {
    throw new Error('No CDP page target found');
  }
  return page.webSocketDebuggerUrl;
}

class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.ws.once('open', resolve);
      this.ws.once('error', reject);
      this.ws.on('message', (raw) => this.handleMessage(raw));
      this.ws.on('close', () => {
        for (const { reject: rejectPending } of this.pending.values()) {
          rejectPending(new Error('CDP socket closed'));
        }
        this.pending.clear();
      });
    });
  }

  handleMessage(raw) {
    const message = JSON.parse(raw.toString());
    if (message.id && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) {
        reject(new Error(message.error.message || JSON.stringify(message.error)));
      } else {
        resolve(message.result || {});
      }
      return;
    }

    if (message.method && this.listeners.has(message.method)) {
      for (const listener of this.listeners.get(message.method)) {
        listener(message.params || {});
      }
    }
  }

  send(method, params = {}) {
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    this.ws.send(payload);
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP command timed out: ${method}`));
        }
      }, 30000);
    });
  }

  on(method, listener) {
    if (!this.listeners.has(method)) {
      this.listeners.set(method, new Set());
    }
    this.listeners.get(method).add(listener);
  }

  close() {
    this.ws.close();
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForLoadEvent(client, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    client.on('Page.loadEventFired', () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

async function smoothScroll(client, durationMs) {
  const steps = Math.floor(durationMs / 80);
  for (let i = 0; i < steps; i++) {
    await client.send('Input.dispatchMouseEvent', {
      type: 'mouseWheel',
      x: Math.floor(WIDTH / 2),
      y: Math.floor(HEIGHT / 2),
      deltaY: 95,
      deltaX: 0,
      modifiers: 0,
      pointerType: 'mouse'
    });
    await sleep(80);
  }
}

function toCookieParam(cookie) {
  const result = {
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain,
    path: cookie.path || '/',
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly)
  };
  if (cookie.sameSite && ['Strict', 'Lax', 'None'].includes(cookie.sameSite)) {
    result.sameSite = cookie.sameSite;
  }
  if (!cookie.session && Number.isFinite(cookie.expires) && cookie.expires > 0) {
    result.expires = cookie.expires;
  }
  return result;
}

async function restoreAuthCookies(client) {
  if (!fs.existsSync(AUTH_STATE_PATH)) {
    log(`No auth_state.json found at ${AUTH_STATE_PATH}; recording as anonymous session`);
    return null;
  }

  const authState = JSON.parse(await fsp.readFile(AUTH_STATE_PATH, 'utf8'));
  const cookies = Array.isArray(authState.cookies)
    ? authState.cookies.filter((cookie) => cookie && cookie.name && typeof cookie.value === 'string').map(toCookieParam)
    : [];

  if (cookies.length > 0) {
    await client.send('Network.setCookies', { cookies });
  }
  log(`Restored auth cookies: ${cookies.length}`);
  return authState;
}

async function restorePageStorage(client, authState) {
  if (!authState || !authState.storageByOrigin) {
    return false;
  }

  const targetOrigin = new URL(TARGET_URL).origin;
  const storage = authState.storageByOrigin[targetOrigin] ||
    authState.storageByOrigin[Object.keys(authState.storageByOrigin)[0]];
  if (!storage) {
    return false;
  }

  const localStorageValues = storage.localStorage || {};
  const sessionStorageValues = storage.sessionStorage || {};
  const localJson = JSON.stringify(localStorageValues);
  const sessionJson = JSON.stringify(sessionStorageValues);
  await client.send('Runtime.evaluate', {
    expression: `
      (() => {
        const localValues = ${localJson};
        const sessionValues = ${sessionJson};
        for (const [key, value] of Object.entries(localValues)) {
          localStorage.setItem(key, value);
        }
        for (const [key, value] of Object.entries(sessionValues)) {
          sessionStorage.setItem(key, value);
        }
        return {
          localStorageKeys: Object.keys(localValues).length,
          sessionStorageKeys: Object.keys(sessionValues).length
        };
      })()
    `,
    returnByValue: true
  });
  log(`Restored localStorage keys: ${Object.keys(localStorageValues).length}`);
  log(`Restored sessionStorage keys: ${Object.keys(sessionStorageValues).length}`);
  return Object.keys(localStorageValues).length > 0 || Object.keys(sessionStorageValues).length > 0;
}

async function buildCfrFrames(frames, durationMs) {
  if (frames.length === 0) {
    throw new Error('No screencast frames captured');
  }

  await fsp.mkdir(CFR_DIR, { recursive: true });
  const durationSeconds = Math.max(durationMs / 1000, frames[frames.length - 1].t);
  const outputFrameCount = Math.max(1, Math.ceil(durationSeconds * FPS));
  let cursor = 0;

  for (let i = 0; i < outputFrameCount; i++) {
    const targetT = i / FPS;
    while (cursor + 1 < frames.length && frames[cursor + 1].t <= targetT) {
      cursor += 1;
    }
    const destination = path.join(CFR_DIR, `frame_${String(i + 1).padStart(6, '0')}.jpg`);
    await fsp.copyFile(frames[cursor].path, destination);
  }

  return outputFrameCount;
}

async function encodeVideo(frameCount) {
  return new Promise((resolve, reject) => {
    const inputPattern = path.join(CFR_DIR, 'frame_%06d.jpg');
    const args = [
      '-y',
      '-framerate', String(FPS),
      '-i', inputPattern,
      '-frames:v', String(frameCount),
      '-c:v', 'libx264',
      '-preset', 'veryfast',
      '-crf', '20',
      '-pix_fmt', 'yuv420p',
      '-movflags', '+faststart',
      VIDEO_PATH
    ];

    log(`ffmpeg ${args.join(' ')}`);
    const ffmpeg = spawn(ffmpegStatic, args, { stdio: ['ignore', 'ignore', 'pipe'] });
    let stderr = '';
    ffmpeg.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
    });
    ffmpeg.on('error', reject);
    ffmpeg.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`FFmpeg failed with code ${code}: ${stderr.slice(-1200)}`));
      }
    });
  });
}

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error('Chrome or Edge executable not found');
}

async function main() {
  await fsp.mkdir(FRAMES_DIR, { recursive: true });
  await fsp.mkdir(PROFILE_DIR, { recursive: true });
  fs.writeFileSync(LOG_PATH, '', 'utf8');

  const chromePath = findChrome();
  log(`Using browser: ${chromePath}`);

  const chromeArgs = [
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE_DIR}`,
    `--window-size=${WIDTH},${HEIGHT}`,
    '--headless=new',
    '--disable-notifications',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--autoplay-policy=no-user-gesture-required',
    '--hide-scrollbars=false',
    'about:blank'
  ];

  const chrome = spawn(chromePath, chromeArgs, {
    stdio: ['ignore', 'ignore', 'pipe'],
    windowsHide: true
  });

  chrome.stderr.on('data', (chunk) => {
    const text = chunk.toString().trim();
    if (text) {
      fs.appendFileSync(LOG_PATH, `[chrome] ${text}\n`, 'utf8');
    }
  });

  let client = null;
  let recordingStart = 0;
  let recordingEnd = 0;
  const frames = [];
  let authStateRestored = false;

  try {
    await waitForChrome(PORT, 10000);
    const wsUrl = await getPageWebSocketUrl(PORT);
    client = new CdpClient(wsUrl);
    await client.connect();

    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await client.send('Network.enable');
    await client.send('Emulation.setDeviceMetricsOverride', {
      width: WIDTH,
      height: HEIGHT,
      deviceScaleFactor: 1,
      mobile: false
    });

    const authState = await restoreAuthCookies(client);

    client.on('Page.screencastFrame', async (params) => {
      try {
        await client.send('Page.screencastFrameAck', { sessionId: params.sessionId });
        if (!recordingStart) {
          return;
        }
        const t = (Date.now() - recordingStart) / 1000;
        const framePath = path.join(FRAMES_DIR, `frame_${String(frames.length + 1).padStart(6, '0')}.jpg`);
        await fsp.writeFile(framePath, Buffer.from(params.data, 'base64'));
        frames.push({ path: framePath, t, timestamp: params.metadata && params.metadata.timestamp });
      } catch (err) {
        log(`Frame write error: ${err.message}`);
      }
    });

    log(`Navigating to ${TARGET_URL}`);
    let loadPromise = waitForLoadEvent(client, 30000);
    await client.send('Page.navigate', { url: TARGET_URL });
    await loadPromise;
    const restoredStorage = await restorePageStorage(client, authState);
    if (authState || restoredStorage) {
      authStateRestored = true;
      loadPromise = waitForLoadEvent(client, 30000);
      await client.send('Page.reload', { ignoreCache: false });
      await loadPromise;
    }
    await sleep(2500);

    log('Starting Page.startScreencast');
    recordingStart = Date.now();
    await client.send('Page.startScreencast', {
      format: 'jpeg',
      quality: QUALITY,
      maxWidth: WIDTH,
      maxHeight: HEIGHT,
      everyNthFrame: 1
    });

    await sleep(1200);
    log('Scrolling page');
    await smoothScroll(client, 9000);
    await sleep(1500);

    recordingEnd = Date.now();
    await client.send('Page.stopScreencast').catch(() => {});
    log(`Captured ${frames.length} raw screencast frames`);

    const durationMs = recordingEnd - recordingStart;
    const cfrFrameCount = await buildCfrFrames(frames, durationMs);
    await encodeVideo(cfrFrameCount);

    const metadata = {
      taskId: TASK_ID,
      url: TARGET_URL,
      captureMode: 'cdp_page_start_screencast',
      resolution: `${WIDTH}x${HEIGHT}`,
      fps: FPS,
      rawFrameCount: frames.length,
      cfrFrameCount,
      durationMs,
      profileId: PROFILE_ID,
      authStateRestored,
      videoPath: VIDEO_PATH,
      createdAt: new Date().toISOString()
    };
    await fsp.writeFile(path.join(OUT_DIR, 'metadata.json'), JSON.stringify(metadata, null, 2), 'utf8');
    log(`Video written: ${VIDEO_PATH}`);
  } finally {
    if (client) {
      client.close();
    }
    if (!chrome.killed) {
      chrome.kill();
    }
  }
}

main().catch((err) => {
  log(`ERROR: ${err.stack || err.message}`);
  process.exitCode = 1;
});
