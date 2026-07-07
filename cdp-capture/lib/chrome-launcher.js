'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { findChrome, waitForChrome, getPageWebSocketUrl, sleep, ensureDir } = require('./utils');
const { CdpClient } = require('./cdp-client');

/**
 * Launch Chrome with CDP debugging and return a handle.
 *
 * @param {object} options
 * @param {string} options.profileDir  - user-data-dir for Chrome profile
 * @param {number} options.port        - remote debugging port (default 9333)
 * @param {number} options.width       - window width (default 1920)
 * @param {number} options.height      - window height (default 1080)
 * @param {string} options.mode        - 'headless' | 'visible' (default 'headless')
 * @param {string[]} options.extraArgs - additional Chrome args
 * @param {string} options.startUrl    - URL to open at startup (default 'about:blank')
 * @param {function} options.onStderr  - callback for Chrome stderr lines
 * @returns {Promise<{process, port, profileDir, client: CdpClient}>}
 */
async function launchChrome(options = {}) {
  const port = options.port || 9333;
  const width = options.width || 1920;
  const height = options.height || 1080;
  const mode = options.mode || 'headless';
  const extraArgs = options.extraArgs || [];
  const startUrl = options.startUrl || 'about:blank';
  const profileDir = options.profileDir;

  if (!profileDir) {
    throw new Error('profileDir is required');
  }

  await ensureDir(profileDir);

  const chromePath = findChrome();

  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    `--window-size=${width},${height}`,
    '--disable-notifications',
    '--autoplay-policy=no-user-gesture-required',
    '--no-first-run',
    '--no-default-browser-check',
  ];

  if (mode === 'headless') {
    args.push('--headless=new');
    args.push('--disable-background-timer-throttling');
    args.push('--disable-backgrounding-occluded-windows');
    args.push('--disable-renderer-backgrounding');
    args.push('--hide-scrollbars=false');
  }

  args.push(...extraArgs);
  args.push(startUrl);

  const stdioMode = mode === 'headless'
    ? ['ignore', 'ignore', 'pipe']
    : 'inherit';

  const chrome = spawn(chromePath, args, {
    stdio: stdioMode,
    windowsHide: mode === 'headless',
  });

  if (options.onStderr && chrome.stderr) {
    chrome.stderr.on('data', (chunk) => {
      const text = chunk.toString().trim();
      if (text) {
        options.onStderr(text);
      }
    });
  }

  // Wait for CDP
  await waitForChrome(port, 15000);

  // Connect to the page target
  const wsUrl = await getPageWebSocketUrl(port);
  const client = new CdpClient(wsUrl);
  await client.connect();

  return {
    process: chrome,
    port,
    profileDir,
    client,
    chromePath,
  };
}

/**
 * Gracefully close Chrome and the CDP connection.
 */
async function closeChrome(handle) {
  if (!handle) return;
  try {
    if (handle.client) {
      await handle.client.send('Browser.close').catch(() => {});
      handle.client.close();
    }
  } catch (_e) {
    // ignore
  }
  if (handle.process && !handle.process.killed) {
    handle.process.kill();
  }
}

module.exports = { launchChrome, closeChrome };
