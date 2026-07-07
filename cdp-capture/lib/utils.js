'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const path = require('node:path');

// ── sleep ────────────────────────────────────────────────────────────────────
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── findChrome ───────────────────────────────────────────────────────────────
function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    `${process.env.LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe`,
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  throw new Error(
    'Chrome or Edge executable not found. Set CHROME_PATH env or install Chrome.'
  );
}

// ── findFfmpeg ───────────────────────────────────────────────────────────────
function findFfmpeg() {
  // 1) Try local require
  try {
    return require('ffmpeg-static');
  } catch (_e) {
    // fall through
  }
  // 2) Try openbridge-desktop
  try {
    return require('../../openbridge-desktop/node_modules/ffmpeg-static');
  } catch (_e2) {
    // fall through
  }
  // 3) Try system ffmpeg
  return 'ffmpeg';
}

// ── HTTP JSON helper ─────────────────────────────────────────────────────────
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
    req.setTimeout(2000, () => {
      req.destroy(new Error(`Timeout requesting ${url}`));
    });
  });
}

// ── waitForChrome ────────────────────────────────────────────────────────────
async function waitForChrome(port, timeoutMs = 15000) {
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

// ── getPageWebSocketUrl ──────────────────────────────────────────────────────
async function getPageWebSocketUrl(port) {
  const targets = await requestJson(`http://127.0.0.1:${port}/json/list`);
  const page =
    targets.find((t) => t.type === 'page' && t.url !== 'about:blank') ||
    targets.find((t) => t.type === 'page');
  if (!page || !page.webSocketDebuggerUrl) {
    throw new Error('No CDP page target found');
  }
  return page.webSocketDebuggerUrl;
}

// ── generateTaskId ───────────────────────────────────────────────────────────
function generateTaskId() {
  const now = new Date();
  return `task-${now
    .toISOString()
    .replace(/[:.]/g, '-')
    .replace('T', '_')
    .slice(0, 23)}`;
}

// ── ensureDir ────────────────────────────────────────────────────────────────
async function ensureDir(dir) {
  await fsp.mkdir(dir, { recursive: true });
  return dir;
}

// ── resolveModule (try local, fallback to openbridge-desktop) ────────────────
function resolveModule(name) {
  try {
    return require(name);
  } catch (_e) {
    return require(path.join(__dirname, '..', '..', 'openbridge-desktop', 'node_modules', name));
  }
}

// ── toCookieParam ────────────────────────────────────────────────────────────
function toCookieParam(cookie) {
  const result = {
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain,
    path: cookie.path || '/',
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly),
  };
  if (cookie.sameSite && ['Strict', 'Lax', 'None'].includes(cookie.sameSite)) {
    result.sameSite = cookie.sameSite;
  }
  if (!cookie.session && Number.isFinite(cookie.expires) && cookie.expires > 0) {
    result.expires = cookie.expires;
  }
  return result;
}

module.exports = {
  sleep,
  findChrome,
  findFfmpeg,
  requestJson,
  waitForChrome,
  getPageWebSocketUrl,
  generateTaskId,
  ensureDir,
  resolveModule,
  toCookieParam,
};
