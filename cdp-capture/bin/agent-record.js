#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { launchChrome, closeChrome } = require('../lib/chrome-launcher');
const { ensureDir, sleep } = require('../lib/utils');

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith('--')) continue;
    const key = item.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
    } else {
      args[key] = next;
      index += 1;
    }
  }
  return args;
}

function quoteConcatPath(value) {
  return value.replace(/'/g, "'\\''");
}

async function waitForLoad(client, timeoutMs = 30000) {
  await new Promise((resolve, reject) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      off();
      resolve();
    };
    const off = client.on('Page.loadEventFired', finish);
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      off();
      reject(new Error(`page load timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
}

async function evaluate(client, expression, awaitPromise = true) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    awaitPromise,
    returnByValue: true,
    userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'Runtime.evaluate failed');
  }
  return result.result ? result.result.value : undefined;
}

async function waitForSelector(client, selector, timeoutMs = 30000) {
  const expression = `new Promise((resolve, reject) => {
    const selector = ${JSON.stringify(selector)};
    const deadline = Date.now() + ${Number(timeoutMs)};
    const poll = () => {
      const node = document.querySelector(selector);
      if (node) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('selector timeout: ' + selector));
      setTimeout(poll, 100);
    };
    poll();
  })`;
  await evaluate(client, expression, true);
}

async function ensureCursor(client) {
  await evaluate(client, `(() => {
    let cursor = document.getElementById('__agent_test_cursor__');
    if (!cursor) {
      cursor = document.createElement('div');
      cursor.id = '__agent_test_cursor__';
      Object.assign(cursor.style, {
        position: 'fixed', width: '26px', height: '26px', borderRadius: '50%',
        border: '4px solid rgba(255,70,70,.95)', background: 'rgba(255,255,255,.25)',
        boxShadow: '0 0 0 8px rgba(255,70,70,.18)', pointerEvents: 'none',
        zIndex: '2147483647', transform: 'translate(-50%, -50%)',
        transition: 'left 180ms ease, top 180ms ease, transform 120ms ease'
      });
      document.documentElement.appendChild(cursor);
    }
    return true;
  })()`);
}

async function targetCenter(client, selector) {
  return evaluate(client, `(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) throw new Error('selector not found: ' + ${JSON.stringify(selector)});
    node.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
    const rect = node.getBoundingClientRect();
    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
  })()`);
}

async function moveCursor(client, point, click = false) {
  await ensureCursor(client);
  await evaluate(client, `(() => {
    const cursor = document.getElementById('__agent_test_cursor__');
    cursor.style.left = ${Number(point.x)} + 'px';
    cursor.style.top = ${Number(point.y)} + 'px';
    cursor.style.transform = 'translate(-50%, -50%) scale(${click ? 0.72 : 1})';
    setTimeout(() => { cursor.style.transform = 'translate(-50%, -50%) scale(1)'; }, 160);
  })()`);
  await client.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: point.x, y: point.y });
  if (click) {
    await sleep(180);
    await client.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
    await client.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  }
}

async function runStep(client, step) {
  const type = String(step.type || '').trim();
  if (type === 'goto' || type === 'open') {
    const loaded = waitForLoad(client, step.timeout_ms || 30000).catch(() => {});
    await client.send('Page.navigate', { url: step.url });
    await loaded;
    return;
  }
  if (type === 'wait') {
    await sleep(Number(step.ms || step.duration_ms || 1000));
    return;
  }
  if (type === 'wait_for_selector') {
    await waitForSelector(client, step.selector, step.timeout_ms || 30000);
    return;
  }
  if (type === 'click') {
    await waitForSelector(client, step.selector, step.timeout_ms || 30000);
    const point = await targetCenter(client, step.selector);
    await moveCursor(client, point, true);
    await sleep(Number(step.after_ms || 500));
    return;
  }
  if (type === 'fill') {
    await waitForSelector(client, step.selector, step.timeout_ms || 30000);
    const point = await targetCenter(client, step.selector);
    await moveCursor(client, point, true);
    await evaluate(client, `(() => {
      const node = document.querySelector(${JSON.stringify(step.selector)});
      const value = ${JSON.stringify(String(step.value ?? ''))};
      const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), 'value');
      if (descriptor && descriptor.set) descriptor.set.call(node, value); else node.value = value;
      node.dispatchEvent(new Event('input', {bubbles: true}));
      node.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    })()`);
    await sleep(Number(step.after_ms || 350));
    return;
  }
  if (type === 'select') {
    await waitForSelector(client, step.selector, step.timeout_ms || 30000);
    await evaluate(client, `(() => {
      const node = document.querySelector(${JSON.stringify(step.selector)});
      node.value = ${JSON.stringify(String(step.value ?? ''))};
      node.dispatchEvent(new Event('input', {bubbles: true}));
      node.dispatchEvent(new Event('change', {bubbles: true}));
      return true;
    })()`);
    await sleep(Number(step.after_ms || 350));
    return;
  }
  if (type === 'scroll') {
    await evaluate(client, `window.scrollTo({top: ${Number(step.y || 0)}, left: ${Number(step.x || 0)}, behavior: 'smooth'})`);
    await sleep(Number(step.after_ms || 650));
    return;
  }
  if (type === 'key') {
    const key = String(step.key || 'Enter');
    await client.send('Input.dispatchKeyEvent', { type: 'keyDown', key });
    await client.send('Input.dispatchKeyEvent', { type: 'keyUp', key });
    await sleep(Number(step.after_ms || 300));
    return;
  }
  if (type === 'evaluate') {
    await evaluate(client, String(step.expression || 'true'));
    await sleep(Number(step.after_ms || 100));
    return;
  }
  throw new Error(`unsupported recipe step type: ${type}`);
}

async function record(recipePath, outputDir) {
  const recipe = JSON.parse(await fsp.readFile(recipePath, 'utf8'));
  const width = Number(recipe.width || 1440);
  const height = Number(recipe.height || 900);
  const fps = Number(recipe.fps || 30);
  const quality = Number(recipe.jpeg_quality || 82);
  const profileId = String(recipe.profile_id || 'agent-test');
  const profileDir = path.resolve(__dirname, '..', 'profiles', profileId);
  const framesDir = path.join(outputDir, 'frames');
  await ensureDir(framesDir);

  const handle = await launchChrome({
    profileDir,
    port: Number(recipe.port || 9444),
    width,
    height,
    mode: recipe.mode || 'visible',
    startUrl: recipe.start_url || 'about:blank',
  });
  const { client } = handle;
  const frames = [];
  const writes = [];
  let index = 0;

  try {
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await client.send('DOM.enable');
    await client.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await ensureCursor(client).catch(() => {});

    client.on('Page.screencastFrame', (event) => {
      const frameIndex = index++;
      const filename = `frame_${String(frameIndex).padStart(6, '0')}.jpg`;
      const framePath = path.join(framesDir, filename);
      const timestamp = event.metadata && Number(event.metadata.timestamp) > 0
        ? Number(event.metadata.timestamp)
        : Date.now() / 1000;
      frames.push({ framePath, timestamp });
      writes.push(fsp.writeFile(framePath, Buffer.from(event.data, 'base64')));
      client.send('Page.screencastFrameAck', { sessionId: event.sessionId }).catch(() => {});
    });

    await client.send('Page.startScreencast', {
      format: 'jpeg',
      quality,
      maxWidth: width,
      maxHeight: height,
      everyNthFrame: 1,
    });
    await sleep(Number(recipe.lead_in_ms || 650));

    for (const step of recipe.steps || []) {
      await runStep(client, step);
    }
    await sleep(Number(recipe.tail_ms || 900));
    await client.send('Page.stopScreencast');
    await Promise.all(writes);
  } finally {
    await closeChrome(handle);
  }

  if (frames.length < 2) {
    throw new Error(`CDP screencast captured too few frames: ${frames.length}`);
  }

  const concatPath = path.join(outputDir, 'frames.ffconcat');
  const concatLines = ['ffconcat version 1.0'];
  for (let i = 0; i < frames.length; i += 1) {
    const current = frames[i];
    const next = frames[i + 1];
    const duration = next ? Math.max(1 / fps, next.timestamp - current.timestamp) : 1 / fps;
    concatLines.push(`file '${quoteConcatPath(path.resolve(current.framePath))}'`);
    concatLines.push(`duration ${duration.toFixed(6)}`);
  }
  concatLines.push(`file '${quoteConcatPath(path.resolve(frames[frames.length - 1].framePath))}'`);
  await fsp.writeFile(concatPath, concatLines.join('\n') + '\n', 'utf8');

  const recordingPath = path.join(outputDir, 'recording.mp4');
  const ffmpeg = spawnSync('ffmpeg', [
    '-y', '-v', 'warning', '-f', 'concat', '-safe', '0', '-i', concatPath,
    '-vf', `fps=${fps},format=yuv420p`, '-c:v', 'libx264', '-preset', 'veryfast',
    '-movflags', '+faststart', recordingPath,
  ], { stdio: 'inherit' });
  if (ffmpeg.status !== 0) {
    throw new Error(`ffmpeg failed with status ${ffmpeg.status}`);
  }

  await fsp.writeFile(path.join(outputDir, 'capture_report.json'), JSON.stringify({
    recipe: path.resolve(recipePath),
    recording: path.resolve(recordingPath),
    frame_count: frames.length,
    width,
    height,
    fps,
  }, null, 2), 'utf8');
  return recordingPath;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.recipe || !args.output) {
    console.error('Usage: node bin/agent-record.js --recipe <recipe.json> --output <directory>');
    process.exitCode = 2;
    return;
  }
  const recipePath = path.resolve(args.recipe);
  const outputDir = path.resolve(args.output);
  await ensureDir(outputDir);
  const recording = await record(recipePath, outputDir);
  console.log(JSON.stringify({ recording }, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
