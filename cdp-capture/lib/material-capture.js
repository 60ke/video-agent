'use strict';

/**
 * CDP Material Capture Engine
 *
 * Captures clean screenshots from the website WITHOUT video recording.
 * Callout coordinates are collected in-memory and optionally mirrored to a
 * local callout registry so downstream case registration can reuse the exact
 * CDP target boxes instead of guessing from OCR/LLM text.
 *
 * Output structure (all files in a flat assets/sites/ directory):
 *   assets/sites/
 *     柯幻熊猫_网站_主页_原始桌面截图.jpg
 *     柯幻熊猫_文生图_<label>_功能入口截图.png
 *     柯幻熊猫_文生图_<label>_参数面板截图.png
 *
 * Per cdp_screenshot_material_spec.md:
 *   - CDP only opens pages, reuses auth, hover/click/scroll, takes clean screenshots
 *   - Red boxes, arrows, cursor circles, click pulses are NOT burned in — passed as callouts
 *   - Callouts use normalized coordinates (0-1 ratio of screenshot dimensions)
 */

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const { launchChrome, closeChrome } = require('./chrome-launcher');
const { restoreAuthState, getProfileDir, getAuthStatePath } = require('./profile-auth');
const { requiredFormScript } = require('./actions');
const { sleep, ensureDir } = require('./utils');

// ── Constants ────────────────────────────────────────────────────────────────

const DEFAULT_ORIGIN = 'https://www.kehuanxiongmao.com';
const DEFAULT_PROFILE_ID = 'kehuanxiongmao';
const DEFAULT_VIEWPORT = { width: 1920, height: 1080 };
const DEFAULT_CHROME_PORT = 9342;
const SITE_LABEL = '柯幻熊猫';
const SITE_ID = 'kehuanxiongmao';
const CALLOUT_REGISTRY_FILENAME = '_callouts.json';
const MODULE_REGISTRY_RELATIVE = path.join(
  '..',
  'references',
  'site_profiles',
  'kehuanxiongmao_text_to_image_modules.json'
);

// ── Helpers ──────────────────────────────────────────────────────────────────

function loadModuleRegistry(cdpCaptureRoot) {
  const registryPath = path.resolve(cdpCaptureRoot, MODULE_REGISTRY_RELATIVE);
  if (!fs.existsSync(registryPath)) {
    throw new Error(`Module registry not found: ${registryPath}`);
  }
  return JSON.parse(fs.readFileSync(registryPath, 'utf8'));
}

function findModule(registry, moduleIdOrAlias) {
  const needle = String(moduleIdOrAlias).toLowerCase().trim();
  const modules = registry.modules || [];
  return (
    modules.find(
      (m) =>
        m.id.toLowerCase() === needle ||
        m.label.toLowerCase() === needle ||
        (Array.isArray(m.aliases) && m.aliases.some((a) => a.toLowerCase() === needle))
    ) || null
  );
}

async function evaluate(client, expression) {
  const result = await client.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    const desc =
      result.exceptionDetails.exception && result.exceptionDetails.exception.description
        ? result.exceptionDetails.exception.description
        : result.exceptionDetails.text || 'evaluation failed';
    throw new Error(desc);
  }
  return result.result && result.result.value;
}

async function waitForLoadEvent(client, timeoutMs = 30000) {
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        resolve(false);
      }
    }, timeoutMs);
    client.once('Page.loadEventFired', () => {
      if (!settled) {
        clearTimeout(timer);
        settled = true;
        resolve(true);
      }
    });
  });
}

async function waitForCondition(client, expression, label, timeoutMs = 10000, intervalMs = 200) {
  const deadline = Date.now() + timeoutMs;
  let lastValue = null;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const value = await evaluate(client, expression);
      lastValue = value;
      if (value === true || (value && value.ok === true)) {
        return value;
      }
    } catch (err) {
      lastError = err;
    }
    await sleep(intervalMs);
  }
  const detail = lastError ? lastError.message : JSON.stringify(lastValue);
  throw new Error(`${label} timed out: ${detail}`);
}

async function waitForAnimationSettle(client, frames = 3) {
  await evaluate(client, `new Promise((resolve) => {
    let left = ${Number(frames) || 3};
    const tick = () => {
      left -= 1;
      if (left <= 0) resolve(true);
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  })`);
}

async function navigateAndSettle(client, url, authResult = null, settleMs = 1200) {
  const loadPromise = waitForLoadEvent(client, 30000);
  await client.send('Page.navigate', { url });
  await loadPromise;
  if (authResult && typeof authResult.storageRestored === 'function') {
    await authResult.storageRestored();
  }
  await sleep(settleMs);
  await waitForAnimationSettle(client).catch(() => {});
}

async function waitForHomepageReady(client) {
  return await waitForCondition(
    client,
    `(() => {
      const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) !== 0 && r.width > 0 && r.height > 0;
      };
      const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4, button')];
      const hasTextToImageNav = els.some((el) => visible(el) && normalize(el.textContent) === '文生图');
      const hasHome = els.some((el) => visible(el) && normalize(el.textContent) === '首页');
      return { ok: location.pathname === '/' && hasTextToImageNav && hasHome,
        path: location.pathname, hasTextToImageNav, hasHome };
    })()`,
    'homepage ready'
  );
}

async function clearHoverMenus(client) {
  const viewport = await getViewportSize(client).catch(() => DEFAULT_VIEWPORT);
  await client.send('Input.dispatchMouseEvent', {
    type: 'mouseMoved',
    x: Math.max(0, viewport.width - 24),
    y: Math.max(0, viewport.height - 24),
  });
  await waitForCondition(
    client,
    `(() => {
      const visible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0.02 && r.width > 0 && r.height > 0;
      };
      const visiblePanels = [...document.querySelectorAll('.hover-submenu-panel, .child-panel')]
        .filter(visible);
      return { ok: visiblePanels.length === 0, visiblePanels: visiblePanels.length };
    })()`,
    'hover menu hidden',
    5000,
    120
  );
  await waitForAnimationSettle(client).catch(() => {});
}

async function waitForHoverMenuTarget(client, targetLabel, options = {}) {
  const childOnly = Boolean(options.childOnly);
  return await waitForCondition(
    client,
    `(() => {
      const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
      const targetLabel = ${JSON.stringify(targetLabel)};
      const childOnly = ${childOnly ? 'true' : 'false'};
      const visible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0.1 && r.width > 0 && r.height > 0;
      };
      const panels = [...document.querySelectorAll(childOnly ? '.child-panel, .hover-submenu-panel.child-panel' : '.hover-submenu-panel')]
        .filter(visible);
      const panel = panels[0] || null;
      const candidates = panels.flatMap((panelEl) => [...panelEl.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4, button')])
        .filter((el) => visible(el) && normalize(el.textContent) === targetLabel);
      const target = candidates.sort((a, b) =>
        (a.getBoundingClientRect().width * a.getBoundingClientRect().height) -
        (b.getBoundingClientRect().width * b.getBoundingClientRect().height)
      )[0] || null;
      const panelRect = panel ? panel.getBoundingClientRect() : null;
      const targetRect = target ? target.getBoundingClientRect() : null;
      return {
        ok: Boolean(panel && target),
        panelCount: panels.length,
        targetFound: Boolean(target),
        panelRect: panelRect ? {
          x: Math.round(panelRect.x), y: Math.round(panelRect.y),
          w: Math.round(panelRect.width), h: Math.round(panelRect.height),
        } : null,
        targetRect: targetRect ? {
          x: Math.round(targetRect.x), y: Math.round(targetRect.y),
          w: Math.round(targetRect.width), h: Math.round(targetRect.height),
        } : null,
      };
    })()`,
    `hover menu target "${targetLabel}"`,
    6000,
    120
  );
}

async function waitForStableVisiblePanels(client, options = {}) {
  const childOnly = Boolean(options.childOnly);
  let previous = null;
  let stableCount = 0;
  const deadline = Date.now() + (options.timeoutMs || 5000);
  while (Date.now() < deadline) {
    const current = await evaluate(
      client,
      `(() => {
        const childOnly = ${childOnly ? 'true' : 'false'};
        const visible = (el) => {
          if (!el) return false;
          const style = getComputedStyle(el);
          const r = el.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            Number(style.opacity) > 0.1 && r.width > 0 && r.height > 0;
        };
        return [...document.querySelectorAll(childOnly ? '.child-panel, .hover-submenu-panel.child-panel' : '.hover-submenu-panel')]
          .filter(visible)
          .map((el) => {
            const r = el.getBoundingClientRect();
            return {
              x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width), h: Math.round(r.height),
              opacity: Math.round(Number(getComputedStyle(el).opacity || 1) * 100) / 100,
            };
          });
      })()`
    );
    const signature = JSON.stringify(current || []);
    if (signature === previous && current && current.length > 0) {
      stableCount += 1;
      if (stableCount >= 2) {
        return current;
      }
    } else {
      stableCount = 0;
      previous = signature;
    }
    await sleep(120);
  }
  throw new Error('hover menu panel did not stabilize');
}

async function waitForFeaturePageReady(client, mod) {
  const routePath = new URL(mod.route, DEFAULT_ORIGIN).pathname;
  return await waitForCondition(
    client,
    `(() => {
      const normalize = (v) => String(v || '').replace(/\\s+/g, '').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) !== 0 && r.width > 0 && r.height > 0;
      };
      const expectedTitle = normalize(${JSON.stringify(mod.page_title || '')});
      const expectedLabel = normalize(${JSON.stringify(mod.label || '')});
      const titleEl = document.querySelector('.label-active');
      const title = titleEl ? normalize(titleEl.textContent || '') : '';
      const titleOk = Boolean(title) &&
        (title === expectedTitle || title === expectedLabel || title.includes(expectedLabel) || expectedTitle.includes(title));
      const leftPanel = document.querySelector('.left-panel-wrap');
      const contentBox = document.querySelector('.content-box');
      const els = [...document.querySelectorAll('button, [role="button"], a, div, span')];
      const hasGenerate = els.some((el) => visible(el) &&
        String(el.textContent || '').replace(/\\s+/g, '').includes('开始生成'));
      return {
        ok: location.pathname === ${JSON.stringify(routePath)} && titleOk && hasGenerate,
        path: location.pathname,
        expectedPath: ${JSON.stringify(routePath)},
        title,
        expectedTitle,
        expectedLabel,
        titleOk,
        hasLeftPanel: Boolean(leftPanel),
        hasContentBox: Boolean(contentBox),
        hasGenerate,
      };
    })()`,
    `feature page ready "${mod.label}"`,
    12000,
    200
  );
}

/**
 * Take a full-viewport JPEG screenshot.
 */
async function takeViewportScreenshot(client, filepath) {
  const { data } = await client.send('Page.captureScreenshot', {
    format: 'jpeg',
    quality: 95,
  });
  await fsp.writeFile(filepath, Buffer.from(data, 'base64'));
  return filepath;
}

/**
 * Take a PNG screenshot of a specific DOM element (by selector).
 * Falls back to full viewport if the selector is not found.
 */
async function takeElementScreenshot(client, selector, filepath, options = {}) {
  // Get element clip rect
  const rect = await evaluate(client, `(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height,
             scaleX: window.devicePixelRatio || 1, scaleY: window.devicePixelRatio || 1 };
  })()`);

  if (rect && rect.width > 0 && rect.height > 0) {
    const { data } = await client.send('Page.captureScreenshot', {
      format: 'png',
      clip: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        scale: rect.scaleX,
      },
    });
    await fsp.writeFile(filepath, Buffer.from(data, 'base64'));
  } else if (options.allowFallback === false) {
    throw new Error(`element not available for screenshot: ${selector}`);
  } else {
    // Fallback: full viewport PNG
    const { data } = await client.send('Page.captureScreenshot', { format: 'png' });
    await fsp.writeFile(filepath, Buffer.from(data, 'base64'));
  }
  return filepath;
}

/**
 * Get the viewport dimensions for coordinate normalization.
 */
async function getViewportSize(client) {
  return await evaluate(client, `({ width: window.innerWidth, height: window.innerHeight })`);
}

/**
 * Get the bounding rect of an element matching text content.
 * Returns normalized coordinates (0-1) relative to viewport.
 */
async function getElementNormalizedRect(client, targetText, options = {}) {
  const exact = options.exact !== false;
  const script = `(() => {
    const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
    const targetText = ${JSON.stringify(targetText)};
    const visible = (el) => {
      if (!el) return false;
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        Number(style.opacity) !== 0 && r.width > 0 && r.height > 0;
    };
    const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4, button, label')];
    const candidates = els.filter((el) => {
      if (!visible(el)) return false;
      const text = normalize(el.textContent);
      return ${exact ? 'text === targetText' : 'text.includes(targetText) && text.length <= 20'};
    });
    if (candidates.length === 0) return null;
    // Pick the smallest visible match (the actual element, not a container)
    const target = candidates.sort((a, b) =>
      (a.getBoundingClientRect().width * a.getBoundingClientRect().height) -
      (b.getBoundingClientRect().width * b.getBoundingClientRect().height)
    )[0];
    const r = target.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return {
      x: r.x / vw,
      y: r.y / vh,
      w: r.width / vw,
      h: r.height / vh,
      px_x: r.x,
      px_y: r.y,
      px_w: r.width,
      px_h: r.height,
      text: normalize(target.textContent),
    };
  })()`;
  return await evaluate(client, script);
}

/**
 * Get a text element rect normalized against a container screenshot.
 * Use this when the saved screenshot is an element crop rather than viewport.
 */
async function getElementNormalizedRectInContainer(client, targetText, containerSelector, options = {}) {
  const exact = options.exact !== false;
  const maxTextLength = Number(options.maxTextLength || 32);
  const script = `(() => {
    const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
    const targetText = ${JSON.stringify(targetText)};
    const container = document.querySelector(${JSON.stringify(containerSelector)});
    if (!container) return null;
    const containerRect = container.getBoundingClientRect();
    if (containerRect.width <= 0 || containerRect.height <= 0) return null;
    const visible = (el) => {
      if (!el) return false;
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        Number(style.opacity) !== 0 && r.width > 0 && r.height > 0;
    };
    const els = [...container.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4, button, label, input, textarea')];
    const candidates = els.filter((el) => {
      if (!visible(el)) return false;
      const text = normalize(el.textContent || el.getAttribute('placeholder') || el.value || '');
      return ${exact ? 'text === targetText' : `text.includes(targetText) && text.length <= ${maxTextLength}`};
    });
    if (candidates.length === 0) return null;
    const target = candidates.sort((a, b) =>
      (a.getBoundingClientRect().width * a.getBoundingClientRect().height) -
      (b.getBoundingClientRect().width * b.getBoundingClientRect().height)
    )[0];
    const r = target.getBoundingClientRect();
    return {
      x: (r.x - containerRect.x) / containerRect.width,
      y: (r.y - containerRect.y) / containerRect.height,
      w: r.width / containerRect.width,
      h: r.height / containerRect.height,
      px_x: r.x - containerRect.x,
      px_y: r.y - containerRect.y,
      px_w: r.width,
      px_h: r.height,
      text: normalize(target.textContent || target.getAttribute('placeholder') || target.value || ''),
      coordinate_space: 'element_screenshot_normalized',
      container_selector: ${JSON.stringify(containerSelector)},
    };
  })()`;
  return await evaluate(client, script);
}

/**
 * Get the target item inside the currently visible hover menu panels.
 * This avoids duplicate-label mistakes where the same feature text appears in
 * both the hero card and the opened submenu.
 */
async function getHoverMenuItemNormalizedRect(client, targetText, options = {}) {
  const childOnly = Boolean(options.childOnly);
  const script = `(() => {
    const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
    const targetText = ${JSON.stringify(targetText)};
    const childOnly = ${childOnly ? 'true' : 'false'};
    const visible = (el) => {
      if (!el) return false;
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        Number(style.opacity) > 0.1 && r.width > 0 && r.height > 0;
    };
    const selector = childOnly
      ? '.child-panel, .hover-submenu-panel.child-panel'
      : '.hover-submenu-panel';
    const panels = [...document.querySelectorAll(selector)].filter(visible);
    const candidates = panels.flatMap((panel) =>
      [...panel.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4, button')]
        .map((el) => ({ panel, el }))
    ).filter(({ el }) => visible(el) && normalize(el.textContent) === targetText);
    if (candidates.length === 0) return null;
    const selected = candidates.sort((a, b) =>
      (a.el.getBoundingClientRect().width * a.el.getBoundingClientRect().height) -
      (b.el.getBoundingClientRect().width * b.el.getBoundingClientRect().height)
    )[0];
    const r = selected.el.getBoundingClientRect();
    const panelRect = selected.panel.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return {
      x: r.x / vw,
      y: r.y / vh,
      w: r.width / vw,
      h: r.height / vh,
      px_x: r.x,
      px_y: r.y,
      px_w: r.width,
      px_h: r.height,
      text: normalize(selected.el.textContent),
      target_role: childOnly ? 'nested_hover_menu_child' : 'hover_menu_child',
      panel_box: {
        x: panelRect.x / vw,
        y: panelRect.y / vh,
        w: panelRect.width / vw,
        h: panelRect.height / vh,
      },
      coordinate_space: 'viewport_screenshot_normalized',
    };
  })()`;
  return await evaluate(client, script);
}

function normalizeCallout(callout) {
  if (!callout || !callout.box) return null;
  const box = callout.box;
  const normalized = {
    ...callout,
    box: {
      x: Math.max(0, Math.min(1, Number(box.x) || 0)),
      y: Math.max(0, Math.min(1, Number(box.y) || 0)),
      w: Math.max(0.01, Math.min(1, Number(box.w) || 0.01)),
      h: Math.max(0.01, Math.min(1, Number(box.h) || 0.01)),
    },
  };
  if (!normalized.coordinate_space) {
    normalized.coordinate_space = 'source_image_normalized';
  }
  return normalized;
}

function calloutRegistryPath(outputDir, explicitPath = null) {
  return explicitPath ? path.resolve(explicitPath) : path.join(outputDir, CALLOUT_REGISTRY_FILENAME);
}

async function writeCalloutRegistry(outputDir, assets, explicitPath = null) {
  const registryPath = calloutRegistryPath(outputDir, explicitPath);
  let registry = { schema_version: 1, source: 'cdp_material_capture', items: {} };
  if (fs.existsSync(registryPath)) {
    try {
      registry = JSON.parse(await fsp.readFile(registryPath, 'utf8'));
    } catch {
      registry = { schema_version: 1, source: 'cdp_material_capture', items: {} };
    }
  }
  if (!registry || typeof registry !== 'object') {
    registry = { schema_version: 1, source: 'cdp_material_capture', items: {} };
  }
  if (!registry.items || typeof registry.items !== 'object' || Array.isArray(registry.items)) {
    registry.items = {};
  }
  for (const asset of assets) {
    if (!asset || !asset.filename || !Array.isArray(asset.callouts)) continue;
    const callouts = asset.callouts.map(normalizeCallout).filter(Boolean);
    registry.items[asset.filename] = {
      filename: asset.filename,
      asset_kind: asset.asset_kind || '',
      capture_type: asset.capture_type || '',
      feature_label: asset.feature_label || '',
      feature_path: asset.feature_path || [],
      callouts,
      updated_at: new Date().toISOString(),
    };
  }
  registry.updated_at = new Date().toISOString();
  await ensureDir(path.dirname(registryPath));
  await fsp.writeFile(registryPath, JSON.stringify(registry, null, 2) + '\n', 'utf8');
  return registryPath;
}

// ── Capture functions ────────────────────────────────────────────────────────

/**
 * Capture the site homepage screenshot.
 * @param {object} client - CDP client
 * @param {string} origin - site origin URL
 * @param {object} authResult - auth restore result
 * @param {string} outputDir - assets/sites directory (flat)
 * @returns {Promise<object>} asset metadata
 */
async function captureHomepage(client, origin, authResult, outputDir) {
  process.stderr.write('  Capturing homepage...\n');

  // Navigate to homepage
  await navigateAndSettle(client, origin + '/', authResult, 1800);
  await waitForHomepageReady(client);
  await clearHoverMenus(client).catch(() => {});

  // Scroll to top
  await evaluate(client, 'window.scrollTo(0, 0)');
  await sleep(500);

  // Check auth
  const authCheck = await evaluate(client, `(() => {
    const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
    const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4')];
    const found = els.some((el) =>
      (el.offsetParent || el.tagName === 'BODY') && normalize(el.textContent) === '文生图'
    );
    return { logged_in: found };
  })()`);

  if (!authCheck || !authCheck.logged_in) {
    throw new Error('Auth check failed: 文生图 nav not visible on homepage. User may not be logged in.');
  }

  // Take screenshot
  const filename = `${SITE_LABEL}_网站_主页_原始桌面截图.jpg`;
  const filepath = path.join(outputDir, filename);
  await takeViewportScreenshot(client, filepath);

  // Get callout coordinates
  const callouts = [];
  const entryCallout = await getElementNormalizedRect(client, '文生图', { exact: true });
  if (entryCallout) {
    callouts.push({
      type: 'highlight_box',
      target_label: '文生图',
      intent: 'highlight_module_entry',
      box: { x: entryCallout.x, y: entryCallout.y, w: entryCallout.w, h: entryCallout.h },
      coordinate_space: 'source_image_normalized',
    });
  }
  const resourceCallout = await getElementNormalizedRect(client, '案例资源库', { exact: true });
  if (resourceCallout) {
    callouts.push({
      type: 'highlight_box',
      target_label: '案例资源库',
      intent: 'highlight_resource_library',
      box: { x: resourceCallout.x, y: resourceCallout.y, w: resourceCallout.w, h: resourceCallout.h },
      coordinate_space: 'source_image_normalized',
    });
  }

  const viewport = await getViewportSize(client);

  const asset = {
    asset_id: `${SITE_ID}_site_home_raw_desktop`,
    filename,
    site: SITE_ID,
    site_label: SITE_LABEL,
    source_level_1: 'site',
    asset_kind: 'site_home',
    visual_state: 'raw',
    capture_type: '网站主页截图',
    route: '/',
    viewport: `${viewport.width}x${viewport.height}`,
    path: filename,
    callouts,
    captured_at: new Date().toISOString(),
  };

  process.stderr.write(`  ✓ Homepage: ${filename}\n`);
  return asset;
}

/**
 * Hover 文生图 and capture the feature entry screenshot with submenu expanded.
 * @param {object} client
 * @param {object} mod - module definition
 * @param {string} outputDir - assets/sites directory (flat)
 * @returns {Promise<object>} asset metadata
 */
async function captureFeatureEntry(client, mod, outputDir) {
  process.stderr.write(`  Capturing feature entry (hover menu)...\n`);

  await waitForHomepageReady(client);
  await clearHoverMenus(client).catch(() => {});

  // We should be on the homepage already. Hover 文生图 to expand the submenu.
  // Use mouse dispatch to trigger hover
  const navRect = await evaluate(client, `(() => {
    const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
    const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4')];
    const target = els.find((el) =>
      (el.offsetParent || el.tagName === 'BODY') && normalize(el.textContent) === '文生图'
    );
    if (!target) return null;
    const r = target.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  })()`);

  if (!navRect) {
    throw new Error('Could not find 文生图 element to hover');
  }

  // Dispatch mouse events to trigger hover
  await client.send('Input.dispatchMouseEvent', {
    type: 'mouseMoved',
    x: navRect.x,
    y: navRect.y,
  });
  await waitForHoverMenuTarget(client, mod.label);
  await waitForStableVisiblePanels(client);
  await waitForAnimationSettle(client);

  // Take screenshot of the viewport (showing the expanded menu)
  const filename = `${SITE_LABEL}_文生图_${mod.label.replace(/[/\\]/g, '_')}_功能入口截图.png`;
  const filepath = path.join(outputDir, filename);
  await takeViewportScreenshot(client, filepath);

  // Get callouts for the module item in the submenu
  const callouts = [];
  const navEntryCallout = await getElementNormalizedRect(client, '文生图', { exact: true });
  if (navEntryCallout) {
    callouts.push({
      type: 'highlight_box',
      target_label: '文生图',
      intent: 'hover_entry',
      box: { x: navEntryCallout.x, y: navEntryCallout.y, w: navEntryCallout.w, h: navEntryCallout.h },
      target_role: 'left_nav_entry',
      coordinate_space: 'source_image_normalized',
    });
  }
  const moduleCallout = await getHoverMenuItemNormalizedRect(client, mod.label);
  if (moduleCallout) {
    callouts.push({
      type: 'pulse_ring',
      target_label: mod.label,
      intent: 'click_target',
      box: { x: moduleCallout.x, y: moduleCallout.y, w: moduleCallout.w, h: moduleCallout.h },
      target_role: moduleCallout.target_role || 'hover_menu_child',
      panel_box: moduleCallout.panel_box || null,
      coordinate_space: 'source_image_normalized',
    });
  }

  const viewport = await getViewportSize(client);

  const asset = {
    asset_id: `${SITE_ID}_tti_${mod.id}_001_feature_entry`,
    filename,
    site: SITE_ID,
    site_label: SITE_LABEL,
    source_level_1: 'text_to_image',
    module: mod.id,
    module_label: mod.label,
    asset_kind: 'feature_entry',
    visual_state: 'raw',
    capture_type: '功能入口截图',
    route: '/',
    feature_label: mod.label,
    viewport: `${viewport.width}x${viewport.height}`,
    path: filename,
    callouts,
    captured_at: new Date().toISOString(),
  };

  process.stderr.write(`  ✓ Feature entry: ${filename}\n`);
  return asset;
}

/**
 * Click the module label to navigate, then capture the parameter panel screenshot.
 * @param {object} client
 * @param {object} mod
 * @param {string} origin
 * @param {string} outputDir - assets/sites directory (flat)
 * @returns {Promise<object>} asset metadata
 */
async function captureFeatureParams(client, mod, origin, outputDir) {
  process.stderr.write(`  Capturing feature params (left panel)...\n`);

  await clearHoverMenus(client).catch(() => {});

  // Navigate directly to the module route and wait for the actual SPA state,
  // not just a load event. Page.loadEventFired is too weak for this app.
  const moduleUrl = origin + mod.route;
  await navigateAndSettle(client, moduleUrl, null, 1500);
  await waitForFeaturePageReady(client, mod);
  await clearHoverMenus(client).catch(() => {});
  await waitForFeaturePageReady(client, mod);

  // Scroll .content-box to top (if exists)
  await evaluate(client, `(() => {
    const box = document.querySelector('.content-box');
    if (box) box.scrollTop = 0;
    window.scrollTo(0, 0);
  })()`);
  await sleep(500);

  // Close any open dropdowns, popups, toasts
  await evaluate(client, `(() => {
    // Click outside to close dropdowns
    document.body.click();
    // Remove toast elements
    document.querySelectorAll('.el-message, .el-notification, .el-popper').forEach(el => el.remove());
  })()`);
  await sleep(300);

  // Take screenshot of .left-panel-wrap (element screenshot)
  const filename = `${SITE_LABEL}_文生图_${mod.label.replace(/[/\\]/g, '_')}_参数面板截图.png`;
  const filepath = path.join(outputDir, filename);

  // Try element screenshot first, fall back to viewport only after the target
  // route/title has already been verified.
  const panelSelector = '.left-panel-wrap';
  const panelExists = await evaluate(client, `(() => {
    const el = document.querySelector(${JSON.stringify(panelSelector)});
    return el ? { exists: true, width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height } : { exists: false };
  })()`);

  const usedPanelScreenshot = Boolean(panelExists && panelExists.exists && panelExists.width > 0);
  if (usedPanelScreenshot) {
    await takeElementScreenshot(client, panelSelector, filepath, { allowFallback: false });
  } else {
    process.stderr.write(`  ⚠ .left-panel-wrap not found on verified target page, using viewport screenshot\n`);
    await takeViewportScreenshot(client, filepath);
  }

  // Inspect form structure for callouts
  const formScript = requiredFormScript({ mode: 'inspect', includeOptional: true });
  const formResult = await evaluate(client, formScript);

  const callouts = [];

  // Add callouts for required fields
  if (formResult && Array.isArray(formResult.fields)) {
    const requiredFields = formResult.fields.filter((f) => f.required);
    for (const field of requiredFields) {
      // Try to get the normalized rect for this field's label
      const fieldRect = usedPanelScreenshot
        ? await getElementNormalizedRectInContainer(client, field.label, panelSelector, { exact: false })
        : await getElementNormalizedRect(client, field.label, { exact: false });
      if (fieldRect) {
        callouts.push({
          type: 'highlight_box',
          target_label: field.label,
          intent: 'required_field',
          box: { x: fieldRect.x, y: fieldRect.y, w: fieldRect.w, h: fieldRect.h },
          coordinate_space: 'source_image_normalized',
          target_role: 'required_form_field',
        });
      }
    }
  }

  // Add callout for the generate button
  const generateButtonRect = await evaluate(client, `(() => {
    const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
    const visible = (el) => {
      if (!el) return false;
      const style = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' &&
        Number(style.opacity) !== 0 && r.width > 0 && r.height > 0;
    };
    const candidates = [...document.querySelectorAll('button, [role="button"], a, div, span')]
      .filter((el) => visible(el) && normalize(el.textContent).includes('开始生成') && normalize(el.textContent).length <= 20);
    if (candidates.length === 0) return null;
    const btn = candidates[0].closest('button') || candidates[0];
    const r = btn.getBoundingClientRect();
    const useContainer = ${usedPanelScreenshot ? 'true' : 'false'};
    const container = document.querySelector(${JSON.stringify(panelSelector)});
    if (useContainer && container) {
      const cr = container.getBoundingClientRect();
      return { x: (r.x - cr.x) / cr.width, y: (r.y - cr.y) / cr.height, w: r.width / cr.width, h: r.height / cr.height };
    }
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return { x: r.x / vw, y: r.y / vh, w: r.width / vw, h: r.height / vh };
  })()`);

  if (generateButtonRect) {
    callouts.push({
      type: 'pulse_ring',
      target_label: '开始生成',
      intent: 'submit_action',
      box: generateButtonRect,
      coordinate_space: 'source_image_normalized',
      target_role: 'generate_button',
    });
  }

  const viewport = await getViewportSize(client);

  const asset = {
    asset_id: `${SITE_ID}_tti_${mod.id}_001_params_clean`,
    filename,
    site: SITE_ID,
    site_label: SITE_LABEL,
    source_level_1: 'text_to_image',
    module: mod.id,
    module_label: mod.label,
    asset_kind: 'feature_form_params',
    visual_state: 'raw',
    capture_type: '参数面板截图',
    route: mod.route,
    feature_label: mod.label,
    viewport: `${viewport.width}x${viewport.height}`,
    path: filename,
    callouts,
    form_details: formResult
      ? {
          total_fields: formResult.fields ? formResult.fields.length : 0,
          required_fields: formResult.fields
            ? formResult.fields
                .filter((f) => f.required)
                .map((f) => ({ label: f.label, type: f.type, filled: f.filled }))
            : [],
          generate_button: formResult.generateButton || null,
        }
      : null,
    captured_at: new Date().toISOString(),
  };

  process.stderr.write(`  ✓ Feature params: ${filename}\n`);
  if (formResult && formResult.fields) {
    const reqCount = formResult.fields.filter((f) => f.required).length;
    process.stderr.write(`    Form: ${formResult.fields.length} fields, ${reqCount} required\n`);
  }
  return asset;
}

/**
 * Capture feature entry for a graphic-ad child module.
 * Requires hovering 文生图, then clicking/hovering 图文广告 to expand the child panel.
 * @param {object} client
 * @param {object} child - child module definition
 * @param {string} outputDir - assets/sites directory (flat)
 * @returns {Promise<object>} asset metadata
 */
async function captureGraphicAdChildEntry(client, child, outputDir) {
  process.stderr.write(`  Capturing graphic-ad child entry: ${child.label}...
`);

  await waitForHomepageReady(client);

  // We should be on the homepage with 文生图 submenu already open from prior steps.
  // Hover/click 图文广告 to expand the child panel.
  const gaRect = await evaluate(client, `(() => {
    const normalize = (v) => String(v || '').replace(/\s+/g, ' ').trim();
    const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4')];
    const target = els.find((el) =>
      (el.offsetParent || el.tagName === 'BODY') && normalize(el.textContent) === '图文广告'
    );
    if (!target) return null;
    const r = target.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  })()`);

  if (!gaRect) {
    throw new Error('Could not find 图文广告 element to hover');
  }

  // Move mouse to 图文广告 to trigger child panel
  await client.send('Input.dispatchMouseEvent', {
    type: 'mouseMoved',
    x: gaRect.x,
    y: gaRect.y,
  });
  await waitForHoverMenuTarget(client, child.label, { childOnly: true });
  await waitForStableVisiblePanels(client, { childOnly: true });
  await waitForAnimationSettle(client);

  // Take screenshot showing the expanded child panel
  const safeLabel = child.label.replace(/[/\\]/g, '_');
  const filename = `${SITE_LABEL}_文生图_图文广告_${safeLabel}_功能入口截图.png`;
  const filepath = path.join(outputDir, filename);
  await takeViewportScreenshot(client, filepath);

  // Get callouts
  const callouts = [];
  const gaCallout = await getElementNormalizedRect(client, '图文广告', { exact: true });
  if (gaCallout) {
    callouts.push({
      type: 'highlight_box',
      target_label: '图文广告',
      intent: 'hover_entry',
      box: { x: gaCallout.x, y: gaCallout.y, w: gaCallout.w, h: gaCallout.h },
      target_role: 'hover_menu_parent',
      coordinate_space: 'source_image_normalized',
    });
  }
  const childCallout = await getHoverMenuItemNormalizedRect(client, child.label, { childOnly: true });
  if (childCallout) {
    callouts.push({
      type: 'pulse_ring',
      target_label: child.label,
      intent: 'click_target',
      box: { x: childCallout.x, y: childCallout.y, w: childCallout.w, h: childCallout.h },
      target_role: childCallout.target_role || 'nested_hover_menu_child',
      panel_box: childCallout.panel_box || null,
      coordinate_space: 'source_image_normalized',
    });
  }

  const viewport = await getViewportSize(client);
  const asset = {
    asset_id: `${SITE_ID}_ga_${child.id}_feature_entry`,
    filename,
    site: SITE_ID,
    site_label: SITE_LABEL,
    source_level_1: 'graphic_ad',
    module: child.id,
    module_label: child.label,
    asset_kind: 'feature_entry',
    visual_state: 'raw',
    capture_type: '功能入口截图',
    route: '/textToImage',
    feature_label: child.label,
    viewport: `${viewport.width}x${viewport.height}`,
    path: filename,
    callouts,
    captured_at: new Date().toISOString(),
  };

  process.stderr.write(`  ✓ Graphic-ad child entry: ${filename}\n`);
  return asset;
}

// ── Main capture orchestrator ────────────────────────────────────────────────

/**
 * Capture materials for one or more modules.
 *
 * @param {object} options
 * @param {string} options.rootDir        - cdp-capture root directory
 * @param {string|string[]} options.modules - module id(s) to capture; '*' for all
 * @param {string} [options.profileId]    - Chrome profile id
 * @param {number} [options.port]         - Chrome debugging port
 * @param {string} [options.mode]         - 'headless' | 'visible'
 * @param {number} [options.width]        - viewport width
 * @param {number} [options.height]       - viewport height
 * @param {string} [options.outputDir]    - assets output directory (default: ../assets/sites)
 * @param {string} [options.calloutRegistry] - local callout registry path
 * @param {boolean} [options.captureHomepage] - capture site homepage (default true)
 * @param {boolean} [options.captureEntry] - capture feature entry (default true)
 * @param {boolean} [options.captureParams] - capture feature params (default true)
 * @returns {Promise<object>} asset metadata plus local callout registry path
 */
async function captureMaterials(options) {
  const rootDir = options.rootDir;
  const registry = loadModuleRegistry(rootDir);
  const profileId = options.profileId || DEFAULT_PROFILE_ID;
  const port = options.port || DEFAULT_CHROME_PORT;
  const mode = options.mode || 'headless';
  const width = options.width || DEFAULT_VIEWPORT.width;
  const height = options.height || DEFAULT_VIEWPORT.height;
  const origin =
    (registry.cdp_navigation_contract &&
      registry.cdp_navigation_contract.canonical_origin) ||
    DEFAULT_ORIGIN;

  // Resolve modules
  let moduleIds = options.modules;
  if (typeof moduleIds === 'string') {
    moduleIds = moduleIds === '*' ? 'all' : [moduleIds];
  }
  if (moduleIds === 'all' || (Array.isArray(moduleIds) && moduleIds.includes('*'))) {
    moduleIds = (registry.modules || []).map((m) => m.id);
  }
  if (!Array.isArray(moduleIds) || moduleIds.length === 0) {
    throw new Error('No modules specified for material capture');
  }

  const modulesToCapture = [];
  const notFound = [];
  for (const id of moduleIds) {
    const mod = findModule(registry, id);
    if (mod) modulesToCapture.push(mod);
    else notFound.push(id);
  }

  // Set up output directory — flat structure: assets/sites/
  const outputDir = options.outputDir
    ? path.resolve(options.outputDir)
    : path.resolve(rootDir, '..', 'assets', 'sites');

  await ensureDir(outputDir);
  const calloutRegistryPathValue = calloutRegistryPath(outputDir, options.calloutRegistry);

  // In-memory asset tracking; screenshots go to assets/sites and callouts are
  // mirrored to a small registry JSON for downstream case registration.
  const assets = [];

  if (notFound.length > 0) {
    process.stderr.write(`⚠ Unknown module ids: ${notFound.join(', ')}\n`);
  }

  if (modulesToCapture.length === 0 && options.captureHomepage === false) {
    return { site: SITE_ID, site_label: SITE_LABEL, assets };
  }

  // Launch Chrome
  const profileDir = getProfileDir(rootDir, profileId);
  const authStatePath = getAuthStatePath(rootDir, profileId);
  let chromeHandle = null;

  try {
    process.stderr.write(`Launching Chrome (${mode}) — profile: ${profileDir}\n`);
    chromeHandle = await launchChrome({
      profileDir,
      port,
      width,
      height,
      mode,
      startUrl: 'about:blank',
    });

    const client = chromeHandle.client;
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await client.send('Network.enable');

    await client.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });

    // Restore auth
    const authResult = await restoreAuthState(client, {
      rootDir,
      profileId,
      targetUrl: origin,
      log: (msg) => process.stderr.write(`  ${msg}\n`),
    });

    if (!authResult.authState) {
      throw new Error(`No auth_state.json found at ${authStatePath}. Material capture requires login.`);
    }

    // ── Capture homepage ──────────────────────────────────────────────────
    if (options.captureHomepage !== false) {
      process.stderr.write('\n── Capturing Homepage ──\n');
      const homeAsset = await captureHomepage(client, origin, authResult, outputDir);
      assets.push(homeAsset);
    }

    // ── Capture each module ───────────────────────────────────────────────
    for (let i = 0; i < modulesToCapture.length; i++) {
      const mod = modulesToCapture[i];
      process.stderr.write(
        `\n── [${i + 1}/${modulesToCapture.length}] Module: ${mod.id} (${mod.label}) ──\n`
      );

      // Capture feature entry (hover menu)
      if (options.captureEntry !== false) {
        try {
          await navigateAndSettle(client, origin + '/', authResult, 1500);
          await waitForHomepageReady(client);
          const entryAsset = await captureFeatureEntry(client, mod, outputDir);
          assets.push(entryAsset);
        } catch (err) {
          process.stderr.write(`  ✗ Feature entry failed: ${err.message}\n`);
        }
      }

      // For parent modules (e.g. 图文广告), capture children
      if (mod.has_children && registry.graphic_ad_submenu) {
        let children = registry.graphic_ad_submenu.children || [];
        // Filter children if --children option is provided
        if (options.children && Array.isArray(options.children) && options.children.length > 0) {
          children = children.filter((c) =>
            options.children.includes(c.id) ||
            options.children.includes(c.label)
          );
        }
        process.stderr.write(`  Module has ${children.length} children to capture...\n`);

        for (let j = 0; j < children.length; j++) {
          const child = children[j];
          process.stderr.write(`  -- [${j + 1}/${children.length}] Child: ${child.id} (${child.label}) --\n`);

          // Capture child entry (图文广告 sub-menu must be expanded)
          if (options.captureEntry !== false) {
            try {
              // Navigate back to homepage first to reset state
              await navigateAndSettle(client, origin + '/', authResult, 1500);
              await waitForHomepageReady(client);
              await clearHoverMenus(client).catch(() => {});
              await sleep(300);

              // Hover 文生图 to open main submenu (with retry for intermittent hover failures)
              let hoverOk = false;
              for (let attempt = 0; attempt < 3 && !hoverOk; attempt++) {
                if (attempt > 0) {
                  // Move mouse away to reset hover state, then retry
                  await client.send('Input.dispatchMouseEvent', {
                    type: 'mouseMoved', x: 10, y: 10,
                  });
                  await sleep(500);
                  await waitForHomepageReady(client);
                }
                const navRect = await evaluate(client, `(() => {
                  const normalize = (v) => String(v || '').replace(/\s+/g, ' ').trim();
                  const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4')];
                  const target = els.find((el) =>
                    (el.offsetParent || el.tagName === 'BODY') && normalize(el.textContent) === '文生图'
                  );
                  if (!target) return null;
                  const r = target.getBoundingClientRect();
                  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
                })()`);
                if (navRect) {
                  await client.send('Input.dispatchMouseEvent', {
                    type: 'mouseMoved',
                    x: navRect.x,
                    y: navRect.y,
                  });
                  try {
                    await waitForHoverMenuTarget(client, '图文广告');
                    await waitForStableVisiblePanels(client);
                    hoverOk = true;
                  } catch (e) {
                    process.stderr.write(`    ⚠ Hover attempt ${attempt + 1}/3 failed: ${e.message}\n`);
                  }
                }
              }
              if (!hoverOk) {
                throw new Error('Failed to open 文生图 hover menu after 3 attempts');
              }

              const childEntryAsset = await captureGraphicAdChildEntry(client, child, outputDir);
              assets.push(childEntryAsset);
            } catch (err) {
              process.stderr.write(`    ✗ Child entry failed: ${err.message}\n`);
            }
          }

          // Capture child params
          if (options.captureParams !== false) {
            try {
              const childMod = {
                ...child,
                id: child.id,
                label: child.label,
                route: child.route,
                page_title: child.page_title || `图文广告-${child.label}`,
              };
              const childParamsAsset = await captureFeatureParams(client, childMod, origin, outputDir);
              // Override asset_id and source_level_1 for graphic-ad children
              childParamsAsset.asset_id = `${SITE_ID}_ga_${child.id}_params_clean`;
              childParamsAsset.source_level_1 = 'graphic_ad';
              // Override filename to use 图文广告 prefix
              const gaFilename = `${SITE_LABEL}_文生图_图文广告_${child.label.replace(/[/\\]/g, '_')}_参数面板截图.png`;
              const oldPath = path.join(outputDir, childParamsAsset.filename);
              const newPath = path.join(outputDir, gaFilename);
              if (fs.existsSync(oldPath)) {
                fs.renameSync(oldPath, newPath);
              }
              childParamsAsset.filename = gaFilename;
              childParamsAsset.path = gaFilename;
              assets.push(childParamsAsset);
            } catch (err) {
              process.stderr.write(`    ✗ Child params failed: ${err.message}\n`);
            }
          }
        }
        continue; // Skip normal params capture for parent modules
      }

      // Capture feature params (left panel)
      if (options.captureParams !== false) {
        try {
          const paramsAsset = await captureFeatureParams(client, mod, origin, outputDir);
          assets.push(paramsAsset);
        } catch (err) {
          process.stderr.write(`  ✗ Feature params failed: ${err.message}\n`);
        }
      }

    }

    const calloutRegistry = await writeCalloutRegistry(outputDir, assets, options.calloutRegistry);

    // Summary (printed to stderr only)
    process.stderr.write(`\nTotal assets captured: ${assets.length}\n`);
    const summary = { total: assets.length };
    for (const a of assets) {
      const key = a.asset_kind || 'other';
      summary[key] = (summary[key] || 0) + 1;
    }
    process.stderr.write(`Summary: ${JSON.stringify(summary)}\n`);
    process.stderr.write(`Callouts: ${calloutRegistry}\n`);
  } finally {
    if (chromeHandle) {
      process.stderr.write('\nClosing Chrome...\n');
      await closeChrome(chromeHandle);
    }
  }

  return {
    site: SITE_ID,
    site_label: SITE_LABEL,
    assets,
    callout_registry: calloutRegistryPathValue,
  };
}

module.exports = {
  captureMaterials,
  loadModuleRegistry,
  findModule,
};
