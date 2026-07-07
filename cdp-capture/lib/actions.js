'use strict';

const fsp = require('node:fs/promises');
const path = require('node:path');
const { sleep, ensureDir } = require('./utils');
const overlay = require('./overlay');

/**
 * Action executors — each action type has a dedicated function.
 *
 * All executors share a common context:
 * @typedef {object} ActionContext
 * @property {CdpClient} client       - CDP client
 * @property {object} task            - full task config
 * @property {object} viewport        - { width, height }
 * @property {object} overlayConfig   - overlay config (or null if disabled)
 * @property {string} screenshotsDir  - directory for screenshots
 * @property {function} log           - logger function
 */

// ── open_url ─────────────────────────────────────────────────────────────────

async function actionOpenUrl(ctx, action) {
  const url = action.url;
  if (!url) throw new Error('open_url requires "url"');

  // Set up load event listener before navigating
  const loadPromise = waitForLoadEvent(ctx.client, action.timeout || 30000);
  await ctx.client.send('Page.navigate', { url });
  const loaded = await loadPromise;

  // Re-inject overlay after navigation
  if (ctx.overlayConfig) {
    await sleep(500); // give DOM time to settle
    await overlay.injectOverlay(ctx.client, ctx.overlayConfig);
  }

  return { url, loaded };
}

// ── wait ─────────────────────────────────────────────────────────────────────

async function actionWait(ctx, action) {
  const duration = action.duration || 1000;
  await sleep(duration);
  return { duration };
}

// ── scroll ───────────────────────────────────────────────────────────────────

async function actionScroll(ctx, action) {
  const direction = action.direction || 'down';
  const amount = action.amount || 1000;
  const duration = action.duration || 3000;
  const steps = Math.max(1, Math.floor(duration / 80));
  const deltaPerStep = Math.round(amount / steps) * (direction === 'up' ? -1 : 1);

  const centerX = Math.floor(ctx.viewport.width / 2);
  const centerY = Math.floor(ctx.viewport.height / 2);

  // Move cursor to center if overlay is enabled
  if (ctx.overlayConfig) {
    await overlay.moveCursor(ctx.client, centerX, centerY, 300);
  }

  for (let i = 0; i < steps; i++) {
    await ctx.client.send('Input.dispatchMouseEvent', {
      type: 'mouseWheel',
      x: centerX,
      y: centerY,
      deltaY: deltaPerStep,
      deltaX: 0,
      modifiers: 0,
      pointerType: 'mouse',
    });
    await sleep(80);
  }

  return { direction, amount, duration, steps };
}

// ── click_point ──────────────────────────────────────────────────────────────

async function actionClickPoint(ctx, action) {
  const x = action.x;
  const y = action.y;
  const moveDuration = action.moveDuration || 500;

  if (typeof x !== 'number' || typeof y !== 'number') {
    throw new Error('click_point requires numeric "x" and "y"');
  }

  // Animate cursor if overlay is enabled
  if (ctx.overlayConfig) {
    await overlay.moveCursor(ctx.client, x, y, moveDuration);
    await overlay.clickAt(ctx.client, x, y);
    await sleep(100);
  }

  // Send real CDP mouse events
  await ctx.client.send('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x,
    y,
    button: 'left',
    clickCount: 1,
    pointerType: 'mouse',
  });
  await sleep(50);
  await ctx.client.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x,
    y,
    button: 'left',
    clickCount: 1,
    pointerType: 'mouse',
  });

  return { x, y };
}

// ── click_selector ───────────────────────────────────────────────────────────

async function actionClickSelector(ctx, action) {
  const selector = action.selector;
  const moveDuration = action.moveDuration || 500;
  if (!selector) throw new Error('click_selector requires "selector"');

  // Get element rect
  let rect = null;
  if (ctx.overlayConfig) {
    rect = await overlay.getElementRect(ctx.client, selector);
  }
  if (!rect) {
    // Fallback: get rect via direct evaluation
    const result = await ctx.client.send('Runtime.evaluate', {
      expression: `
        (() => {
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height, centerX: r.x + r.width/2, centerY: r.y + r.height/2 };
        })()
      `,
      returnByValue: true,
    });
    rect = result.result && result.result.value;
  }

  if (!rect) {
    throw new Error(`Element not found for selector: ${selector}`);
  }

  const x = Math.round(rect.centerX);
  const y = Math.round(rect.centerY);

  // Animate cursor + highlight if overlay is enabled
  if (ctx.overlayConfig) {
    await overlay.highlightElement(ctx.client, rect, action.highlightDuration || 800);
    await overlay.moveCursor(ctx.client, x, y, moveDuration);
    await overlay.clickAt(ctx.client, x, y);
    await sleep(100);
  }

  // Send real CDP mouse events
  await ctx.client.send('Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x,
    y,
    button: 'left',
    clickCount: 1,
    pointerType: 'mouse',
  });
  await sleep(50);
  await ctx.client.send('Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x,
    y,
    button: 'left',
    clickCount: 1,
    pointerType: 'mouse',
  });

  return { selector, x, y, rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height } };
}

// ── type_text ────────────────────────────────────────────────────────────────

async function actionTypeText(ctx, action) {
  const text = action.text;
  const selector = action.selector;
  const clear = action.clear !== false; // default true
  if (typeof text !== 'string') throw new Error('type_text requires "text"');

  // If selector provided, click on the element first
  if (selector) {
    await actionClickSelector(ctx, {
      type: 'click_selector',
      selector,
      moveDuration: action.moveDuration || 400,
      highlightDuration: 600,
    });
    await sleep(200);

    // Clear existing text
    if (clear) {
      await ctx.client.send('Runtime.evaluate', {
        expression: `
          (() => {
            const el = document.querySelector(${JSON.stringify(selector)});
            if (el && el.value !== undefined) {
              el.value = '';
              el.dispatchEvent(new Event('input', { bubbles: true }));
            }
          })()
        `,
      });
      await sleep(100);
    }
  }

  // Use Input.insertText for typing
  await ctx.client.send('Input.insertText', { text });

  return { selector, text: text.slice(0, 100), length: text.length };
}

// ── evaluate_js ──────────────────────────────────────────────────────────────

async function actionEvaluateJs(ctx, action) {
  const script = action.script;
  const awaitPromise = action.awaitPromise !== false;
  if (!script) throw new Error('evaluate_js requires "script"');

  const result = await ctx.client.send('Runtime.evaluate', {
    expression: script,
    returnByValue: true,
    awaitPromise,
  });

  const value = result.result ? result.result.value : undefined;
  const exceptionDetails = result.exceptionDetails;

  if (exceptionDetails) {
    const errMsg =
      exceptionDetails.exception && exceptionDetails.exception.description
        ? exceptionDetails.exception.description
        : exceptionDetails.text || 'JS evaluation error';
    throw new Error(errMsg);
  }

  return { value };
}

// ── screenshot ───────────────────────────────────────────────────────────────

async function actionScreenshot(ctx, action) {
  const name = action.name || `screenshot-${Date.now()}`;
  await ensureDir(ctx.screenshotsDir);

  const result = await ctx.client.send('Page.captureScreenshot', {
    format: action.format || 'png',
    quality: action.quality,
  });

  const fileName = `${name}.png`;
  const filePath = path.join(ctx.screenshotsDir, fileName);
  await fsp.writeFile(filePath, Buffer.from(result.data, 'base64'));

  return { name, path: filePath };
}

// ── Helper: waitForLoadEvent ─────────────────────────────────────────────────

function waitForLoadEvent(client, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs);
    client.once('Page.loadEventFired', () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

// ── Action dispatcher ────────────────────────────────────────────────────────

const ACTION_HANDLERS = {
  open_url: actionOpenUrl,
  wait: actionWait,
  scroll: actionScroll,
  click_point: actionClickPoint,
  click_selector: actionClickSelector,
  type_text: actionTypeText,
  evaluate_js: actionEvaluateJs,
  screenshot: actionScreenshot,
};

/**
 * Execute a single action.
 * @param {ActionContext} ctx
 * @param {object} action - action config
 * @returns {Promise<object>} action result
 */
async function executeAction(ctx, action) {
  const handler = ACTION_HANDLERS[action.type];
  if (!handler) {
    throw new Error(`Unknown action type: ${action.type}`);
  }
  return handler(ctx, action);
}

module.exports = {
  executeAction,
  ACTION_HANDLERS,
  waitForLoadEvent,
};
