'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const readline = require('node:readline/promises');
const { spawn } = require('node:child_process');
const { findChrome, ensureDir, toCookieParam, sleep } = require('./utils');
const { waitForChrome, getPageWebSocketUrl } = require('./utils');
const { CdpClient } = require('./cdp-client');

// ── Path helpers ─────────────────────────────────────────────────────────────

function getProfileDir(rootDir, profileId) {
  return path.join(rootDir, 'profiles', profileId);
}

function getAuthStatePath(rootDir, profileId) {
  return path.join(getProfileDir(rootDir, profileId), 'auth_state.json');
}

// ── Login (visible Chrome) ───────────────────────────────────────────────────

/**
 * Launch a visible Chrome for manual login, then export auth state.
 *
 * @param {object} options
 * @param {string} options.rootDir    - cdp-capture root dir
 * @param {string} options.profileId  - profile identifier
 * @param {string} options.url        - URL to open for login
 * @param {number} options.port       - CDP port (default 9333)
 * @param {number} options.width      - window width (default 1280)
 * @param {number} options.height     - window height (default 900)
 */
async function loginProfile(options) {
  const { rootDir, profileId, url, port = 9333, width = 1280, height = 900 } = options;
  const profileDir = getProfileDir(rootDir, profileId);
  const authStatePath = getAuthStatePath(rootDir, profileId);

  await ensureDir(profileDir);

  const chromePath = findChrome();
  const chromeArgs = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    `--window-size=${width},${height}`,
    '--disable-notifications',
    '--autoplay-policy=no-user-gesture-required',
    '--no-first-run',
    '--no-default-browser-check',
    url,
  ];

  console.log(`Launching visible Chrome for manual login.`);
  console.log(`URL: ${url}`);
  console.log(`Profile: ${profileDir}`);
  console.log('After login is complete, return to this terminal and press Enter.');

  const chrome = spawn(chromePath, chromeArgs, {
    stdio: 'inherit',
    windowsHide: false,
  });

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await rl.question('Press Enter after the website shows the logged-in state...');
  rl.close();

  // Export auth state
  await exportAuthState(port, profileId, url, authStatePath);

  await new Promise((resolve) => chrome.once('exit', resolve));
  console.log('Chrome closed. Login state is saved in the profile and auth_state.json.');
}

// ── Export auth state via CDP ─────────────────────────────────────────────────

async function exportAuthState(port, profileId, url, authStatePath) {
  await waitForChrome(port, 10000);
  const wsUrl = await getPageWebSocketUrl(port);
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
      `,
    });

    const pageStorage =
      storageResult.result && storageResult.result.value ? storageResult.result.value : {};

    const authState = {
      exportedAt: new Date().toISOString(),
      profileId,
      url,
      currentUrl: pageStorage.href || null,
      cookies: cookiesResult.cookies || [],
      storageByOrigin: {
        [pageStorage.origin || new URL(url).origin]: {
          localStorage: pageStorage.localStorage || {},
          sessionStorage: pageStorage.sessionStorage || {},
        },
      },
    };

    await fsp.writeFile(authStatePath, JSON.stringify(authState, null, 2), 'utf8');
    console.log(`Saved auth state: ${authStatePath}`);
    console.log(`Cookies: ${authState.cookies.length}`);
    console.log(`localStorage keys: ${Object.keys(pageStorage.localStorage || {}).length}`);
    console.log(`sessionStorage keys: ${Object.keys(pageStorage.sessionStorage || {}).length}`);

    await client.send('Browser.close').catch(() => {});
  } finally {
    client.close();
  }
}

// ── Restore auth state ───────────────────────────────────────────────────────

/**
 * Restore cookies and storage from auth_state.json.
 *
 * @param {CdpClient} client
 * @param {object} options
 * @param {string} options.rootDir
 * @param {string} options.profileId
 * @param {string} options.targetUrl  - URL to determine origin for storage
 * @param {function} options.log      - logger function
 * @returns {Promise<{authState: object|null, cookiesRestored: number, storageRestored: boolean}>}
 */
async function restoreAuthState(client, options) {
  const { rootDir, profileId, targetUrl, log } = options;
  const authStatePath = getAuthStatePath(rootDir, profileId);

  if (!fs.existsSync(authStatePath)) {
    log(`No auth_state.json found at ${authStatePath}; continuing without saved login state`);
    return { authState: null, cookiesRestored: 0, storageRestored: false };
  }

  const authState = JSON.parse(await fsp.readFile(authStatePath, 'utf8'));

  // Restore cookies
  const cookies = Array.isArray(authState.cookies)
    ? authState.cookies
        .filter((c) => c && c.name && typeof c.value === 'string')
        .map(toCookieParam)
    : [];

  if (cookies.length > 0) {
    await client.send('Network.setCookies', { cookies });
  }
  log(`Restored auth cookies: ${cookies.length}`);

  // Restore storage (call this after navigation to the target URL)
  const restoreStorage = async () => {
    if (!authState.storageByOrigin) return false;

    const targetOrigin = new URL(targetUrl).origin;
    const storage =
      authState.storageByOrigin[targetOrigin] ||
      authState.storageByOrigin[Object.keys(authState.storageByOrigin)[0]];
    if (!storage) return false;

    const localStorageValues = storage.localStorage || {};
    const sessionStorageValues = storage.sessionStorage || {};
    const localJson = JSON.stringify(localStorageValues);
    const sessionJson = JSON.stringify(sessionStorageValues);

    const result = await client.send('Runtime.evaluate', {
      expression: `
        (() => {
          const localValues = ${localJson};
          const sessionValues = ${sessionJson};
          for (const [key, value] of Object.entries(localValues)) {
            try { localStorage.setItem(key, value); } catch(e) {}
          }
          for (const [key, value] of Object.entries(sessionValues)) {
            try { sessionStorage.setItem(key, value); } catch(e) {}
          }
          return {
            localStorageKeys: Object.keys(localValues).length,
            sessionStorageKeys: Object.keys(sessionValues).length
          };
        })()
      `,
      returnByValue: true,
    });

    const counts = result.result && result.result.value ? result.result.value : {};
    log(`Restored localStorage keys: ${counts.localStorageKeys || 0}`);
    log(`Restored sessionStorage keys: ${counts.sessionStorageKeys || 0}`);
    return (counts.localStorageKeys || 0) > 0 || (counts.sessionStorageKeys || 0) > 0;
  };

  return {
    authState,
    cookiesRestored: cookies.length,
    storageRestored: restoreStorage, // Return function to call after navigation
  };
}

module.exports = {
  loginProfile,
  restoreAuthState,
  getProfileDir,
  getAuthStatePath,
};
