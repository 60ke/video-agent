'use strict';

/**
 * Overlay injection module — injects a Shadow DOM overlay into the page
 * for custom mouse cursor, click ripple, and element highlight animations.
 *
 * The overlay is injected via CDP `Runtime.evaluate` and persists in the page
 * until navigation. Call `injectOverlay` after each navigation to re-inject.
 */

// ── Default overlay config ───────────────────────────────────────────────────
const DEFAULT_OVERLAY_CONFIG = {
  cursor: {
    color: '#ffffff',
    size: 24,
    showTrail: false,
  },
  ripple: {
    color: '#ffffff',
    duration: 600,
  },
  highlight: {
    color: '#ffeb3b',
    duration: 1000,
  },
};

function mergeOverlayConfig(config = {}) {
  return {
    enabled: config.enabled !== false,
    cursor: { ...DEFAULT_OVERLAY_CONFIG.cursor, ...(config.cursor || {}) },
    ripple: { ...DEFAULT_OVERLAY_CONFIG.ripple, ...(config.ripple || {}) },
    highlight: { ...DEFAULT_OVERLAY_CONFIG.highlight, ...(config.highlight || {}) },
  };
}

// ── Overlay injection script ─────────────────────────────────────────────────

function buildOverlayScript(config) {
  const c = JSON.stringify(config);
  return `
(function() {
  if (window.__cdpCaptureOverlay) return true;

  const config = ${c};

  // Create host element with Shadow DOM
  const host = document.createElement('div');
  host.id = 'cdp-capture-overlay-host';
  host.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647;';
  const shadow = host.attachShadow({ mode: 'open' });

  const cursorColor = config.cursor.color;
  const cursorSize = config.cursor.size;
  const rippleColor = config.ripple.color;
  const rippleDuration = config.ripple.duration;
  const highlightColor = config.highlight.color;
  const highlightDuration = config.highlight.duration;
  const showTrail = config.cursor.showTrail;

  shadow.innerHTML = \`
    <style>
      .cdp-cursor {
        position: fixed;
        width: \${cursorSize}px;
        height: \${cursorSize}px;
        border: 2px solid \${cursorColor};
        border-radius: 50%;
        background: rgba(255,255,255,0.12);
        box-shadow: 0 0 8px rgba(0,0,0,0.5), 0 0 0 1px rgba(0,0,0,0.3);
        transform: translate(-50%, -50%);
        transition: left 0ms linear, top 0ms linear, width 0.15s ease, height 0.15s ease, background 0.15s ease;
        pointer-events: none;
        will-change: left, top;
      }
      .cdp-cursor.clicking {
        width: \${cursorSize + 8}px;
        height: \${cursorSize + 8}px;
        background: rgba(255,255,255,0.35);
      }
      .cdp-ripple {
        position: fixed;
        border-radius: 50%;
        border: 2px solid \${rippleColor};
        transform: translate(-50%, -50%);
        pointer-events: none;
        animation: cdp-ripple-expand \${rippleDuration}ms ease-out forwards;
      }
      @keyframes cdp-ripple-expand {
        0% { width: 0; height: 0; opacity: 1; }
        100% { width: \${cursorSize * 3}px; height: \${cursorSize * 3}px; opacity: 0; }
      }
      .cdp-highlight {
        position: fixed;
        border: 2px solid \${highlightColor};
        border-radius: 4px;
        pointer-events: none;
        box-shadow: 0 0 12px \${highlightColor}80;
        transition: opacity 0.3s ease;
      }
      .cdp-trail-dot {
        position: fixed;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: \${cursorColor};
        transform: translate(-50%, -50%);
        pointer-events: none;
        animation: cdp-trail-fade 0.8s ease-out forwards;
      }
      @keyframes cdp-trail-fade {
        0% { opacity: 0.6; }
        100% { opacity: 0; }
      }
    </style>
    <div class="cdp-cursor" id="cdp-cursor" style="display:none;"></div>
  \`;

  // Wait for document.body, then append
  function appendHost() {
    if (document.body) {
      document.body.appendChild(host);
    } else {
      setTimeout(appendHost, 50);
    }
  }
  appendHost();

  const cursor = shadow.getElementById('cdp-cursor');
  let trailInterval = null;

  window.__cdpCaptureOverlay = {
    host,
    shadow,
    cursor,

    showCursor(x, y) {
      cursor.style.display = 'block';
      cursor.style.left = x + 'px';
      cursor.style.top = y + 'px';
    },

    hideCursor() {
      cursor.style.display = 'none';
      if (trailInterval) {
        clearInterval(trailInterval);
        trailInterval = null;
      }
    },

    moveCursor(x, y, duration) {
      cursor.style.display = 'block';

      const startX = parseFloat(cursor.style.left) || 0;
      const startY = parseFloat(cursor.style.top) || 0;
      const stepMs = 16; // ~60fps
      const totalSteps = Math.max(1, Math.ceil(duration / stepMs));
      let step = 0;

      if (showTrail && !trailInterval) {
        trailInterval = setInterval(() => {
          const cx = parseFloat(cursor.style.left);
          const cy = parseFloat(cursor.style.top);
          if (cx != null && cy != null) {
            const dot = document.createElement('div');
            dot.className = 'cdp-trail-dot';
            dot.style.left = cx + 'px';
            dot.style.top = cy + 'px';
            shadow.appendChild(dot);
            setTimeout(() => dot.remove(), 800);
          }
        }, 60);
      }

      function animate() {
        step++;
        const progress = Math.min(step / totalSteps, 1);
        // ease-in-out
        const t = progress < 0.5 ? 2 * progress * progress : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        cursor.style.left = (startX + (x - startX) * t) + 'px';
        cursor.style.top = (startY + (y - startY) * t) + 'px';

        if (step < totalSteps) {
          setTimeout(animate, stepMs);
        } else {
          if (trailInterval) {
            clearInterval(trailInterval);
            trailInterval = null;
          }
        }
      }
      animate();
      // No promise — Node.js side sleeps for the duration
    },

    showRipple(x, y) {
      const ripple = document.createElement('div');
      ripple.className = 'cdp-ripple';
      ripple.style.left = x + 'px';
      ripple.style.top = y + 'px';
      shadow.appendChild(ripple);
      setTimeout(() => ripple.remove(), rippleDuration + 50);
    },

    highlight(rect, duration) {
      const hl = document.createElement('div');
      hl.className = 'cdp-highlight';
      hl.style.left = rect.x + 'px';
      hl.style.top = rect.y + 'px';
      hl.style.width = rect.width + 'px';
      hl.style.height = rect.height + 'px';
      shadow.appendChild(hl);
      setTimeout(() => {
        hl.style.opacity = '0';
        setTimeout(() => hl.remove(), 300);
      }, duration || highlightDuration);
    },

    clickAt(x, y) {
      cursor.classList.add('clicking');
      this.showRipple(x, y);
      setTimeout(() => cursor.classList.remove('clicking'), 200);
    },

    getElementRect(selector) {
      const el = document.querySelector(selector);
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      return {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        centerX: rect.x + rect.width / 2,
        centerY: rect.y + rect.height / 2,
      };
    },
  };

  return true;
})()
`;
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Inject (or re-inject) the overlay into the page.
 * Safe to call multiple times — idempotent.
 */
async function injectOverlay(client, config = {}) {
  const merged = mergeOverlayConfig(config);
  if (!merged.enabled) return false;

  const result = await client.send('Runtime.evaluate', {
    expression: buildOverlayScript(merged),
    returnByValue: true,
  });
  return result.result && result.result.value === true;
}

/**
 * Move the cursor to (x, y) with animation.
 * Uses setTimeout-based animation (not requestAnimationFrame) for headless reliability.
 * The Node.js side sleeps for the duration instead of awaiting a JS Promise.
 */
async function moveCursor(client, x, y, duration = 500) {
  await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.moveCursor(${x}, ${y}, ${duration})`,
    returnByValue: true,
  });
  // Sleep on the Node.js side to let the animation play
  const { sleep } = require('./utils');
  await sleep(duration + 50);
}

/**
 * Show a click ripple at (x, y).
 */
async function showRipple(client, x, y) {
  await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.showRipple(${x}, ${y})`,
    returnByValue: true,
  });
}

/**
 * Highlight an element by its bounding rect.
 */
async function highlightElement(client, rect, duration) {
  await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.highlight(${JSON.stringify(rect)}, ${duration || 1000})`,
    returnByValue: true,
  });
}

/**
 * Animate a click at (x, y): cursor click + ripple.
 */
async function clickAt(client, x, y) {
  await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.clickAt(${x}, ${y})`,
    returnByValue: true,
  });
}

/**
 * Get element bounding rect by selector.
 * @returns {Promise<object|null>} rect with {x, y, width, height, centerX, centerY}
 */
async function getElementRect(client, selector) {
  const result = await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.getElementRect(${JSON.stringify(selector)})`,
    returnByValue: true,
  });
  return result.result && result.result.value ? result.result.value : null;
}

/**
 * Show the cursor at a position.
 */
async function showCursor(client, x, y) {
  await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.showCursor(${x}, ${y})`,
    returnByValue: true,
  });
}

/**
 * Hide the cursor.
 */
async function hideCursor(client) {
  await client.send('Runtime.evaluate', {
    expression: `window.__cdpCaptureOverlay && window.__cdpCaptureOverlay.hideCursor()`,
    returnByValue: true,
  });
}

module.exports = {
  DEFAULT_OVERLAY_CONFIG,
  mergeOverlayConfig,
  injectOverlay,
  moveCursor,
  showRipple,
  highlightElement,
  clickAt,
  getElementRect,
  showCursor,
  hideCursor,
};
