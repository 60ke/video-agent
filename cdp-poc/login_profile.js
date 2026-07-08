const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');
const { spawn } = require('node:child_process');
const readline = require('node:readline/promises');

const WebSocket = require('../openbridge-desktop/node_modules/ws');

const ROOT = __dirname;
const TARGET_URL = process.env.CDP_LOGIN_URL || 'https://www.kehuanxiongmao.com';
const PROFILE_ID = process.env.CDP_PROFILE_ID || 'kehuanxiongmao';
const PROFILE_DIR = path.join(ROOT, 'profiles', PROFILE_ID);
const AUTH_STATE_PATH = path.join(PROFILE_DIR, 'auth_state.json');
const PORT = readPositiveIntEnv('CDP_PORT', 9333);
const WIDTH = readPositiveIntEnv('CDP_WIDTH', 1280);
const HEIGHT = readPositiveIntEnv('CDP_HEIGHT', 900);

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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
  const page = targets.find((target) => target.type === 'page' && target.url !== 'about:blank') ||
    targets.find((target) => target.type === 'page');
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
    }
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
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

  close() {
    this.ws.close();
  }
}

async function exportAuthState() {
  await waitForChrome(PORT, 10000);
  const wsUrl = await getPageWebSocketUrl(PORT);
  const client = new CdpClient(wsUrl);
  await client.connect();
  try {
    await client.send('Network.enable');
    await client.send('Runtime.enable');
    const cookiesResult = await client.send('Network.getAllCookies');
    const storageResult = await client.send('Runtime.evaluate', {
      returnByValue: true,
      expression: `
        (() => {
          const dump = (storage) => {
            const values = {};
            for (let i = 0; i < storage.length; i++) {
              const key = storage.key(i);
              values[key] = storage.getItem(key);
            }
            return values;
          };
          return {
            href: location.href,
            origin: location.origin,
            localStorage: dump(localStorage),
            sessionStorage: dump(sessionStorage)
          };
        })()
      `
    });
    const pageStorage = storageResult.result && storageResult.result.value
      ? storageResult.result.value
      : {};
    const authState = {
      exportedAt: new Date().toISOString(),
      profileId: PROFILE_ID,
      url: TARGET_URL,
      currentUrl: pageStorage.href || null,
      cookies: cookiesResult.cookies || [],
      storageByOrigin: {
        [pageStorage.origin || new URL(TARGET_URL).origin]: {
          localStorage: pageStorage.localStorage || {},
          sessionStorage: pageStorage.sessionStorage || {}
        }
      }
    };
    await fsp.writeFile(AUTH_STATE_PATH, JSON.stringify(authState, null, 2), 'utf8');
    console.log(`Saved auth state: ${AUTH_STATE_PATH}`);
    console.log(`Cookies: ${authState.cookies.length}`);
    console.log(`localStorage keys: ${Object.keys(pageStorage.localStorage || {}).length}`);
    console.log(`sessionStorage keys: ${Object.keys(pageStorage.sessionStorage || {}).length}`);
    await client.send('Browser.close').catch(() => {});
  } finally {
    client.close();
  }
}

async function main() {
  await fsp.mkdir(PROFILE_DIR, { recursive: true });
  const chromePath = findChrome();
  const chromeArgs = [
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE_DIR}`,
    `--window-size=${WIDTH},${HEIGHT}`,
    '--disable-notifications',
    '--autoplay-policy=no-user-gesture-required',
    TARGET_URL
  ];

  console.log(`Launching visible Chrome for manual login.`);
  console.log(`URL: ${TARGET_URL}`);
  console.log(`Profile: ${PROFILE_DIR}`);
  console.log('After login is complete, return to this terminal and press Enter.');

  const chrome = spawn(chromePath, chromeArgs, {
    stdio: 'inherit',
    windowsHide: false
  });

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await rl.question('Press Enter after the website shows the logged-in state...');
  rl.close();

  await exportAuthState();
  await new Promise((resolve) => chrome.once('exit', resolve));
  console.log('Chrome closed. Login state is saved in the profile and auth_state.json.');
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exitCode = 1;
});
