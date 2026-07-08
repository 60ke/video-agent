'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { sleep, ensureDir } = require('./utils');
const overlay = require('./overlay');

// Elements that must never be mistaken for a generated result. A broad result
// selector (e.g. img[src*='img']) otherwise happily matches the site logo,
// avatars, nav icons, or sample/gallery thumbnails.
const DEFAULT_RESULT_EXCLUDE_SELECTORS = [
  'header img',
  'nav img',
  'aside img',
  '.logo img',
  'img.logo',
  'img[src*="logo"]',
  'img[alt*="logo"]',
  'img[alt*="Logo"]',
  'img[class*="avatar"]',
  '[class*="avatar"] img',
  '[class*="header"] img',
  '[class*="Header"] img',
  '[class*="sidebar"] img',
  '[class*="nav"] img',
  '[class*="sample"] img',
  '[class*="example"] img',
  '[class*="demo"] img',
];

// A real generated result should be a reasonably large image. This default
// floor rejects logos/icons/thumbnails when the task does not override it.
const DEFAULT_RESULT_MIN_WIDTH = 240;
const DEFAULT_RESULT_MIN_HEIGHT = 240;
const DEFAULT_RESULT_TIME_TOLERANCE_MS = 0;
const DEFAULT_RESULT_LOADING_SRC_INCLUDES = [
  'generate-loading.a5374121.webp',
  '/static/img/generate-loading',
];

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function stateKey(action, fallback) {
  return typeof action.stateKey === 'string' && action.stateKey.trim()
    ? action.stateKey.trim()
    : fallback;
}

function resultCardScannerExpression(options = {}) {
  const cardSelector = options.cardSelector || '*';
  const imageSelector = options.imageSelector || 'img';
  const excludeSelectors = Array.isArray(options.excludeSelectors) ? options.excludeSelectors : DEFAULT_RESULT_EXCLUDE_SELECTORS;
  const minWidth = isFiniteNumber(options.minWidth) ? options.minWidth : DEFAULT_RESULT_MIN_WIDTH;
  const minHeight = isFiniteNumber(options.minHeight) ? options.minHeight : DEFAULT_RESULT_MIN_HEIGHT;
  const afterMs = isFiniteNumber(options.afterMs) ? options.afterMs : null;
  const toleranceMs = isFiniteNumber(options.toleranceMs) ? options.toleranceMs : DEFAULT_RESULT_TIME_TOLERANCE_MS;
  const loadingSrcIncludes = Array.isArray(options.loadingSrcIncludes)
    ? options.loadingSrcIncludes
    : DEFAULT_RESULT_LOADING_SRC_INCLUDES;
  const allowLoadingImage = options.allowLoadingImage === true;
  const baselineSignatures = Array.isArray(options.baselineSignatures) ? options.baselineSignatures : [];
  const requireImage = options.requireImage === true;
  const requireTextIncludes = Array.isArray(options.requireTextIncludes)
    ? options.requireTextIncludes
    : (typeof options.requireTextIncludes === 'string' ? [options.requireTextIncludes] : []);
  return `
    (() => {
      const cardSelector = ${JSON.stringify(cardSelector)};
      const imageSelector = ${JSON.stringify(imageSelector)};
      const excludes = ${JSON.stringify(excludeSelectors)};
      const minWidth = ${JSON.stringify(minWidth)};
      const minHeight = ${JSON.stringify(minHeight)};
      const afterMs = ${JSON.stringify(afterMs)};
      const toleranceMs = ${JSON.stringify(toleranceMs)};
      const loadingSrcIncludes = ${JSON.stringify(loadingSrcIncludes)};
      const allowLoadingImage = ${JSON.stringify(allowLoadingImage)};
      const baseline = new Set(${JSON.stringify(baselineSignatures)});
      const requireImage = ${JSON.stringify(requireImage)};
      const requireTextIncludes = ${JSON.stringify(requireTextIncludes)};
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const timeRe = /(20\\d{2})[-/.](\\d{1,2})[-/.](\\d{1,2})\\s+(\\d{1,2}):(\\d{1,2})(?::(\\d{1,2}))?/;
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
      };
      const isExcluded = (el) => {
        for (const ex of excludes) {
          try {
            if (el.matches(ex) || el.closest(ex)) return true;
          } catch (_e) {}
        }
        return false;
      };
      const parseTime = (text) => {
        const m = String(text || '').match(timeRe);
        if (!m) return null;
        const ms = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6] || 0)).getTime();
        return Number.isFinite(ms) ? { text: m[0], ms } : null;
      };
      const imageInfo = (card) => {
        const imgs = Array.from(card.querySelectorAll(imageSelector)).filter((img) => {
          if (!visible(img) || isExcluded(img)) return false;
          const src = img.currentSrc || img.src || '';
          if (!allowLoadingImage && loadingSrcIncludes.some((token) => src.includes(String(token)))) return false;
          const r = img.getBoundingClientRect();
          return r.width >= minWidth && r.height >= minHeight;
        }).map((img) => {
          const r = img.getBoundingClientRect();
          return {
            x: r.x, y: r.y, width: r.width, height: r.height,
            centerX: r.x + r.width / 2, centerY: r.y + r.height / 2,
            src: img.currentSrc || img.src || '',
            sourceType: 'img',
            area: r.width * r.height,
          };
        });
        const backgroundEls = Array.from(card.querySelectorAll('*')).filter((el) => {
          if (!visible(el) || isExcluded(el)) return false;
          const r = el.getBoundingClientRect();
          if (r.width < minWidth || r.height < minHeight) return false;
          const bg = window.getComputedStyle(el).backgroundImage || '';
          if (!bg || bg === 'none' || !bg.includes('url(')) return false;
          if (!allowLoadingImage && loadingSrcIncludes.some((token) => bg.includes(String(token)))) return false;
          return true;
        }).map((el) => {
          const r = el.getBoundingClientRect();
          const bg = window.getComputedStyle(el).backgroundImage || '';
          const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
          return {
            x: r.x, y: r.y, width: r.width, height: r.height,
            centerX: r.x + r.width / 2, centerY: r.y + r.height / 2,
            src: match ? match[1] : bg,
            sourceType: 'background-image',
            area: r.width * r.height,
          };
        });
        return imgs.concat(backgroundEls).sort((a, b) => b.area - a.area)[0] || null;
      };
      const normalizeText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
      const signature = (timeText, card, img) => {
        const text = normalizeText(card.textContent).slice(0, 160);
        const src = img && img.src ? img.src : '';
        return [timeText, text, src].join('|');
      };
      let cards = [];
      try { cards = Array.from(document.querySelectorAll(cardSelector)); } catch (_e) { return { error: 'bad_card_selector' }; }
      const candidates = [];
      for (const raw of cards) {
        if (!visible(raw)) continue;
        if (raw === document.body || raw === document.documentElement) continue;
        const rawRect = raw.getBoundingClientRect();
        if (rawRect.width >= vw * 0.9 || rawRect.height >= vh * 0.9) continue;
        const parsed = parseTime(raw.textContent);
        if (!parsed) continue;
        let card = raw;
        let cursor = raw;
        while (cursor && cursor !== document.body) {
          const r = cursor.getBoundingClientRect();
          const text = cursor.textContent || '';
          if (r.width >= 360 && r.height >= 80 && r.width < vw * 0.9 && r.height < vh * 0.9 && parseTime(text)) {
            card = cursor;
            break;
          }
          cursor = cursor.parentElement;
        }
        if (!visible(card)) continue;
        const text = normalizeText(card.textContent);
        if (requireTextIncludes.length && !requireTextIncludes.some((token) => text.includes(String(token)))) continue;
        if (afterMs !== null && parsed.ms < afterMs - toleranceMs) continue;
        const img = imageInfo(card);
        if (requireImage && !img) continue;
        const r = card.getBoundingClientRect();
        const sig = signature(parsed.text, card, img);
        if (baseline.has(sig)) continue;
        candidates.push({
          timestampText: parsed.text,
          timestampMs: parsed.ms,
          text,
          signature: sig,
          rect: { x: r.x, y: r.y, width: r.width, height: r.height, centerX: r.x + r.width / 2, centerY: r.y + r.height / 2 },
          image: img,
        });
      }
      candidates.sort((a, b) => b.timestampMs - a.timestampMs || ((b.image && b.image.area) || 0) - ((a.image && a.image.area) || 0));
      return { candidates };
    })()
  `;
}

async function scanResultCards(ctx, options = {}) {
  const evaluated = await ctx.client.send('Runtime.evaluate', {
    expression: resultCardScannerExpression(options),
    returnByValue: true,
  });
  const value = evaluated.result && evaluated.result.value;
  if (!value || value.error) {
    return [];
  }
  return Array.isArray(value.candidates) ? value.candidates : [];
}

function requiredFormScript(options = {}) {
  const values = options.values && typeof options.values === 'object' ? options.values : {};
  const extraValues = options.extraValues && typeof options.extraValues === 'object' ? options.extraValues : {};
  const mode = options.mode || 'inspect';
  const includeOptional = options.includeOptional === true;
  const generateButtonText = options.generateButtonText || '开始生成';
  return `
    (async () => {
      const mode = ${JSON.stringify(mode)};
      const values = ${JSON.stringify(values)};
      const extraValues = ${JSON.stringify(extraValues)};
      const includeOptional = ${JSON.stringify(includeOptional)};
      const generateButtonText = ${JSON.stringify(generateButtonText)};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const normalize = (value) => String(value || '')
        .replace(/[\\u00a0\\s]+/g, ' ')
        .replace(/[＊*]/g, '')
        .trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < window.innerHeight && r.left < window.innerWidth;
      };
      const rectOf = (el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      };
      const isRedRequiredMark = (el) => {
        const style = window.getComputedStyle(el);
        const color = style.color || '';
        return /rgb\\(\\s*(1[6-9][0-9]|2[0-5][0-9])\\s*,\\s*([0-9]|[1-8][0-9])\\s*,\\s*([0-9]|[1-8][0-9])\\s*\\)/.test(color);
      };
      const fieldContainer = (labelEl) => {
        if (labelEl.querySelector('input, textarea, select, [role="combobox"], .el-select, .el-select__wrapper, .el-cascader')) return labelEl;
        return labelEl.closest('.el-form-item, .ant-form-item, [class*="form-item"], [class*="FormItem"]')
          || labelEl.parentElement?.parentElement
          || labelEl.parentElement
          || labelEl;
      };
      const labelTextFrom = (labelEl) => {
        const clone = labelEl.cloneNode(true);
        for (const node of Array.from(clone.querySelectorAll('input, textarea, select, button, svg, img'))) {
          node.remove();
        }
        return normalize(clone.textContent);
      };
      const isRequiredLabel = (labelEl, container) => {
        if (container.querySelector('[required], [aria-required="true"]')) return true;
        if (container.className && /required|is-required/.test(String(container.className))) return true;
        const text = String(labelEl.textContent || '');
        if (/[＊*]/.test(text)) return true;
        return Array.from(labelEl.querySelectorAll('*')).some((child) => /[＊*]/.test(child.textContent || '') && isRedRequiredMark(child));
      };
      const valueForLabel = (label) => {
        if (Object.prototype.hasOwnProperty.call(values, label)) return values[label];
        if (Object.prototype.hasOwnProperty.call(extraValues, label)) return extraValues[label];
        const compact = label.replace(/\\s+/g, '');
        for (const [key, value] of Object.entries(values)) {
          if (key.replace(/\\s+/g, '') === compact) return value;
        }
        for (const [key, value] of Object.entries(extraValues)) {
          if (key.replace(/\\s+/g, '') === compact) return value;
        }
        const valueEntries = Object.entries(values)
          .map(([key, value]) => [String(key).replace(/\\s+/g, ''), value])
          .sort((a, b) => b[0].length - a[0].length);
        for (const [key, value] of valueEntries) {
          if (compact.startsWith(key) || key.startsWith(compact)) return value;
        }
        const extraEntries = Object.entries(extraValues)
          .map(([key, value]) => [String(key).replace(/\\s+/g, ''), value])
          .sort((a, b) => b[0].length - a[0].length);
        for (const [key, value] of extraEntries) {
          if (compact.startsWith(key) || key.startsWith(compact)) return value;
        }
        return undefined;
      };
      const inputValue = (el) => {
        if (!el) return '';
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return normalize(el.value);
        return normalize(el.textContent);
      };
      const detectControl = (container) => {
        const input = Array.from(container.querySelectorAll('input, textarea, select')).find(visible);
        if (input) {
          const upload = input.type === 'file';
          const customSelect = input.readOnly || Boolean(input.closest('.el-select, .el-select__wrapper, .el-cascader, [role="combobox"]'));
          return {
            type: upload ? 'upload' : (customSelect ? 'select' : (input.tagName === 'TEXTAREA' ? 'textarea' : (input.tagName === 'SELECT' ? 'select' : 'input'))),
            el: input,
            value: inputValue(input),
          };
        }
        const combo = Array.from(container.querySelectorAll('[role="combobox"], .el-select, .el-select__wrapper, .el-cascader, [class*="select"]')).find(visible);
        if (combo) return { type: 'select', el: combo, value: inputValue(combo) };
        const upload = Array.from(container.querySelectorAll('[class*="upload"], [class*="Upload"]')).find(visible);
        if (upload) return { type: 'upload', el: upload, value: inputValue(upload) };
        return { type: 'unknown', el: container, value: inputValue(container) };
      };
      const scan = () => {
        const rawCandidates = [
          ...Array.from(document.querySelectorAll('label, .el-form-item__label, [class*="label"], [class*="Label"]')),
          ...Array.from(document.querySelectorAll('body *')).filter((el) => {
            if (!visible(el)) return false;
            const text = labelTextFrom(el);
            if (!text || text.length > 40) return false;
            const container = fieldContainer(el);
            if (!container || !visible(container)) return false;
            return Boolean(container.querySelector('input, textarea, select, [role="combobox"], .el-select, .el-select__wrapper, .el-cascader, [class*="upload"], [class*="Upload"]'));
          }),
        ];
        const labelCandidates = Array.from(new Set(rawCandidates)).filter(visible);
        const seen = new Set();
        const fields = [];
        for (const labelEl of labelCandidates) {
          const label = labelTextFrom(labelEl);
          if (!label || label.length > 40 || label === generateButtonText) continue;
          const container = fieldContainer(labelEl);
          if (!container || !visible(container)) continue;
          const required = isRequiredLabel(labelEl, container);
          if (!required && !includeOptional && valueForLabel(label) === undefined) continue;
          const key = label + '|' + Math.round(container.getBoundingClientRect().top);
          if (seen.has(key)) continue;
          seen.add(key);
          const control = detectControl(container);
          const placeholder = control.el && (control.el.getAttribute('placeholder') || control.el.getAttribute('aria-placeholder') || '');
          const value = control.value || '';
          const filled = control.type === 'upload'
            ? Boolean(container.querySelector('img, [class*="success"], [class*="uploaded"]'))
            : Boolean(value && !/^请选择|^请输入|^上传/.test(value));
          fields.push({
            label,
            required,
            type: control.type,
            filled,
            value,
            placeholder,
            hasValue: valueForLabel(label) !== undefined,
            rect: rectOf(container),
          });
        }
        const buttons = Array.from(document.querySelectorAll('button, [role="button"], a, div, span'))
          .filter(visible)
          .filter((el) => {
            const text = normalize(el.textContent);
            return text.includes(generateButtonText) && text.length <= 40;
          })
          .sort((a, b) => {
            const ar = a.getBoundingClientRect();
            const br = b.getBoundingClientRect();
            return ar.width * ar.height - br.width * br.height;
          });
        const generateButton = buttons[0] || null;
        const buttonDisabled = generateButton
          ? Boolean(generateButton.disabled || generateButton.getAttribute('aria-disabled') === 'true' || /disabled|is-disabled/.test(String(generateButton.className)))
          : null;
        return { fields, generateButton: generateButton ? { disabled: buttonDisabled, rect: rectOf(generateButton), text: normalize(generateButton.textContent) } : null };
      };
      const setText = (el, value) => {
        const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(el, String(value)); else el.value = String(value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
      };
      const clickLikeUser = (el) => {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        if (typeof el.focus === 'function') el.focus({ preventScroll: true });
        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
          el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
        }
        if (typeof el.click === 'function') el.click();
      };
      const selectOption = async (container, value) => {
        const input = Array.from(container.querySelectorAll('input')).find(visible);
        const trigger = (input && input.closest('.el-select, .el-select__wrapper, .el-cascader, [role="combobox"]'))
          || Array.from(container.querySelectorAll('[role="combobox"], .el-select, .el-select__wrapper, .el-cascader, .el-input, input')).find(visible)
          || container;
        clickLikeUser(trigger);
        await sleep(350);
        const optionSelector = '.el-select-dropdown__item, .el-cascader-node, [role="option"], li, [class*="option"], [class*="Option"]';
        let options = [];
        for (let i = 0; i < 8; i++) {
          options = Array.from(document.querySelectorAll(optionSelector)).filter(visible);
          if (options.length) break;
          await sleep(150);
        }
        const wanted = normalize(value);
        let option = options.find((el) => normalize(el.textContent) === wanted)
          || options.find((el) => normalize(el.textContent).includes(wanted) || wanted.includes(normalize(el.textContent)));
        if (!option) {
          const localOptions = Array.from(container.querySelectorAll('*'))
            .filter((el) => normalize(el.textContent) && normalize(el.textContent).length <= 40);
          option = localOptions.find((el) => normalize(el.textContent) === wanted)
            || localOptions.find((el) => normalize(el.textContent).includes(wanted) || wanted.includes(normalize(el.textContent)));
        }
        if (!option && options.length === 1) option = options[0];
        if (!option) return { ok: false, reason: 'option_not_found', options: options.map((el) => normalize(el.textContent)).filter(Boolean).slice(0, 20) };
        clickLikeUser(option);
        await sleep(250);
        return { ok: true, selected: normalize(option.textContent) };
      };
      const findContainerForLabel = (label) => {
        const wanted = normalize(label);
        const candidates = Array.from(document.querySelectorAll('label, .el-form-item__label, [class*="label"], [class*="Label"], body *'))
          .filter(visible)
          .map((el) => {
            const text = labelTextFrom(el);
            const exact = text === wanted;
            const starts = text.startsWith(wanted) && text.length <= wanted.length + 12;
            if (!exact && !starts) return null;
            const container = fieldContainer(el);
            if (!container || !visible(container)) return null;
            const control = detectControl(container);
            if (!control || control.type === 'unknown') return null;
            const r = container.getBoundingClientRect();
            return { el, container, area: r.width * r.height, exact };
          })
          .filter(Boolean)
          .sort((a, b) => (b.exact === a.exact ? a.area - b.area : (b.exact ? 1 : -1)));
        return candidates[0] ? candidates[0].container : null;
      };
      const fill = async () => {
        const before = scan();
        const actions = [];
        const missingValues = [];
        for (const field of before.fields) {
          if (!field.required && valueForLabel(field.label) === undefined) continue;
          if (field.filled && valueForLabel(field.label) === undefined) continue;
          const value = valueForLabel(field.label);
          if (value === undefined || value === null || String(value).trim() === '') {
            if (field.required && !field.filled) missingValues.push(field.label);
            continue;
          }
          const container = findContainerForLabel(field.label);
          if (!container) {
            actions.push({ label: field.label, ok: false, reason: 'container_not_found' });
            continue;
          }
          const control = detectControl(container);
          if (control.type === 'input' || control.type === 'textarea') {
            setText(control.el, value);
            actions.push({ label: field.label, ok: true, type: control.type, value: String(value) });
          } else if (control.type === 'select') {
            const selected = await selectOption(container, value);
            actions.push({ label: field.label, type: 'select', value: String(value), ...selected });
          } else if (control.type === 'upload') {
            actions.push({ label: field.label, ok: field.filled, type: 'upload', reason: field.filled ? 'already_filled' : 'upload_not_supported_by_required_form' });
          } else {
            actions.push({ label: field.label, ok: false, type: control.type, reason: 'unsupported_control' });
          }
          await sleep(120);
        }
        await sleep(500);
        const after = scan();
        const emptyRequired = after.fields.filter((field) => field.required && !field.filled).map((field) => field.label);
        return { before, actions, after, missingValues, emptyRequired };
      };
      if (mode === 'fill') return fill();
      return scan();
    })()
  `;
}

/**
 * Generate a self-executing JS string that finds and clicks the "开始生成" button.
 *
 * The script:
 *   1. Searches visible elements whose text exactly includes the target text.
 *   2. Filters out disabled elements.
 *   3. Picks the smallest-area match (the actual button, not a large container).
 *   4. Dispatches a full pointer/mouse/click sequence for SPA compatibility.
 *
 * @param {object} options
 * @param {string} options.buttonText  - exact text to match (default '开始生成')
 * @returns {string} inline JS expression
 */
function generateButtonClickScript(options = {}) {
  const buttonText = options.buttonText || '开始生成';
  return `
    (() => {
      const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) !== 0 && r.width > 0 && r.height > 0;
      };
      const candidates = [...document.querySelectorAll('button, [role="button"], a, div, span')]
        .filter((el) => visible(el) &&
          normalize(el.textContent).includes(${JSON.stringify(buttonText)}) &&
          normalize(el.textContent).length <= 20)
        .map((el) => {
          const btn = el.closest('button') || el;
          const r = btn.getBoundingClientRect();
          return {
            el: btn,
            area: r.width * r.height,
            disabled: Boolean(btn.disabled ||
              btn.getAttribute('aria-disabled') === 'true' ||
              /disabled|is-disabled/.test(String(btn.className))),
          };
        })
        .filter((item) => !item.disabled && item.area > 0)
        .sort((a, b) => a.area - b.area);
      const target = candidates[0] && candidates[0].el;
      if (!target) return ${JSON.stringify(buttonText)} + ' not found or disabled';
      target.scrollIntoView({ block: 'center', inline: 'nearest' });
      target.focus?.({ preventScroll: true });
      target.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true, view: window }));
      target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      target.dispatchEvent(new MouseEvent('pointerup', { bubbles: true, cancelable: true, view: window }));
      target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      target.click();
      const r = target.getBoundingClientRect();
      return 'clicked ' + ${JSON.stringify(buttonText)} + ' ' +
        Math.round(r.x) + ',' + Math.round(r.y) + ',' + Math.round(r.width) + 'x' + Math.round(r.height);
    })()
  `;
}

async function evaluateRequiredForm(ctx, options) {
  const evaluated = await ctx.client.send('Runtime.evaluate', {
    expression: requiredFormScript(options),
    returnByValue: true,
    awaitPromise: true,
  });
  if (evaluated.exceptionDetails) {
    const err = evaluated.exceptionDetails.exception && evaluated.exceptionDetails.exception.description
      ? evaluated.exceptionDetails.exception.description
      : evaluated.exceptionDetails.text || 'required form evaluation failed';
    throw new Error(err);
  }
  return evaluated.result && evaluated.result.value;
}

/**
 * Find visible element rects matching a selector.
 *
 * Unlike a raw document.querySelector (first match, any size), this filters out
 * hidden/off-screen/excluded nodes, enforces a minimum size, and can pick the
 * largest match — which is what a genuine generated result usually is.
 *
 * @returns {Promise<object|null>} the chosen rect, or null if nothing qualifies
 */
async function findElementRect(ctx, selector, options = {}) {
  const strategy = options.strategy === 'largest' ? 'largest' : 'first';
  const minWidth = isFiniteNumber(options.minWidth) ? options.minWidth : 0;
  const minHeight = isFiniteNumber(options.minHeight) ? options.minHeight : 0;
  const excludeSelectors = Array.isArray(options.excludeSelectors) ? options.excludeSelectors : [];

  const evaluated = await ctx.client.send('Runtime.evaluate', {
    expression: `
      (() => {
        const sel = ${JSON.stringify(selector)};
        const excludes = ${JSON.stringify(excludeSelectors)};
        const excludeEls = new Set();
        for (const ex of excludes) {
          try { document.querySelectorAll(ex).forEach((el) => excludeEls.add(el)); } catch (_e) {}
        }
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const rects = [];
        let nodes = [];
        try { nodes = Array.from(document.querySelectorAll(sel)); } catch (_e) { return { error: 'bad_selector' }; }
        for (const el of nodes) {
          if (excludeEls.has(el)) continue;
          const style = window.getComputedStyle(el);
          if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) continue;
          const r = el.getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) continue;
          if (r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
          rects.push({
            x: r.x, y: r.y, width: r.width, height: r.height,
            centerX: r.x + r.width / 2, centerY: r.y + r.height / 2,
            tag: el.tagName, src: el.currentSrc || el.src || '',
          });
        }
        return { rects };
      })()
    `,
    returnByValue: true,
  });
  const value = evaluated.result && evaluated.result.value;
  if (!value || value.error === 'bad_selector') {
    return null;
  }
  let rects = Array.isArray(value.rects) ? value.rects : [];
  rects = rects.filter((r) => r.width >= minWidth && r.height >= minHeight);
  if (!rects.length) {
    return null;
  }
  if (strategy === 'largest') {
    rects.sort((a, b) => b.width * b.height - a.width * a.height);
  }
  return rects[0];
}

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
 * @property {string} resultsDir      - directory for generated result captures
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
    if (action.emphasis === 'generate') {
      await overlay.pulseGenerate(ctx.client, { x: x - 80, y: y - 24, width: 160, height: 48 }, action.pulseDuration || 900);
    }
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
    if (action.emphasis === 'generate' || action.generateClick === true) {
      await overlay.pulseGenerate(ctx.client, rect, action.pulseDuration || 900);
    }
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
      cameraFocus: action.cameraFocus,
    });
    await sleep(200);
    if (ctx.overlayConfig) {
      const rect = await overlay.getElementRect(ctx.client, selector);
      if (rect) {
        await overlay.focusInput(ctx.client, rect, action.focusDuration || 650);
      }
    }

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

  if (selector && action.verify !== false) {
    const verifyResult = await ctx.client.send('Runtime.evaluate', {
      expression: `
        (() => {
          const el = document.querySelector(${JSON.stringify(selector)});
          if (!el) return { ok: false, reason: 'missing' };
          const value = el.value !== undefined ? String(el.value) : String(el.textContent || '');
          return { ok: value.includes(${JSON.stringify(text)}) || value.trim().length > 0, value };
        })()
      `,
      returnByValue: true,
    });
    const verification = verifyResult.result && verifyResult.result.value;
    if (!verification || verification.ok !== true) {
      throw new Error(`type_text verification failed for selector: ${selector}`);
    }
  }

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
  const valueText = value === undefined || value === null ? '' : String(value);
  const expectIncludes = Array.isArray(action.expectIncludes)
    ? action.expectIncludes
    : (typeof action.expectIncludes === 'string' ? [action.expectIncludes] : []);
  if (expectIncludes.length > 0 && !expectIncludes.some((token) => valueText.includes(String(token)))) {
    throw new Error(`evaluate_js expected result to include one of ${JSON.stringify(expectIncludes)}, got: ${valueText}`);
  }
  const failIfIncludes = Array.isArray(action.failIfIncludes)
    ? action.failIfIncludes
    : (typeof action.failIfIncludes === 'string' ? [action.failIfIncludes] : []);
  if (failIfIncludes.some((token) => valueText.includes(String(token)))) {
    throw new Error(`evaluate_js result matched failure token ${JSON.stringify(failIfIncludes)}, got: ${valueText}`);
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

// ── capture_element ──────────────────────────────────────────────────────────

async function actionCaptureElement(ctx, action) {
  const selector = action.selector;
  const name = action.name || `element-${Date.now()}`;
  if (!selector) throw new Error('capture_element requires "selector"');

  const isResult = action.resultAsset === true || action.workflowStep === 'result_crop';
  const strategy = action.matchStrategy || (isResult ? 'largest' : 'first');
  const minWidth = isFiniteNumber(action.minWidth)
    ? action.minWidth
    : (isResult ? DEFAULT_RESULT_MIN_WIDTH : 3);
  const minHeight = isFiniteNumber(action.minHeight)
    ? action.minHeight
    : (isResult ? DEFAULT_RESULT_MIN_HEIGHT : 3);
  const excludeSelectors = Array.isArray(action.excludeSelectors)
    ? action.excludeSelectors
    : (isResult ? DEFAULT_RESULT_EXCLUDE_SELECTORS : []);

  const rect = await findElementRect(ctx, selector, { strategy, minWidth, minHeight, excludeSelectors });
  if (!rect) {
    if (isResult) {
      throw new Error(
        `No visible element >= ${minWidth}x${minHeight}px matched result selector: ${selector}. ` +
        'A real generated result must be a sufficiently large image; a logo/icon/thumbnail or an absent ' +
        'result (e.g. an empty "no records" state) is rejected instead of being saved as a fake result. ' +
        'Precede the capture with a wait_for_selector on the real result container.'
      );
    }
    throw new Error(`Element not capturable for selector: ${selector}`);
  }

  const outputDir = isResult ? ctx.resultsDir : ctx.screenshotsDir;
  await ensureDir(outputDir);
  if (ctx.overlayConfig) {
    await overlay.highlightElement(ctx.client, rect, action.highlightDuration || 500);
    await sleep(120);
  }
  const clipX = Math.max(0, Math.min(rect.x, ctx.viewport.width - 1));
  const clipY = Math.max(0, Math.min(rect.y, ctx.viewport.height - 1));
  const clip = {
    x: clipX,
    y: clipY,
    width: Math.max(1, Math.min(rect.width, ctx.viewport.width - clipX)),
    height: Math.max(1, Math.min(rect.height, ctx.viewport.height - clipY)),
    scale: 1,
  };
  const result = await ctx.client.send('Page.captureScreenshot', {
    format: action.format || 'png',
    clip,
  });
  const fileName = `${name}.png`;
  const filePath = path.join(outputDir, fileName);
  await fsp.writeFile(filePath, Buffer.from(result.data, 'base64'));
  return {
    name,
    path: filePath,
    selector,
    match_strategy: strategy,
    matched_tag: rect.tag || null,
    matched_src: rect.src || null,
    rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
    workflow_step: action.workflowStep || (isResult ? 'result_crop' : 'element_capture'),
    result_asset: isResult,
  };
}

// ── result card freshness gates ──────────────────────────────────────────────

async function actionMarkResultBaseline(ctx, action) {
  const key = stateKey(action, 'resultBaseline');
  const cards = await scanResultCards(ctx, {
    cardSelector: action.cardSelector || '*',
    imageSelector: action.imageSelector || 'img',
    excludeSelectors: Array.isArray(action.excludeSelectors) ? action.excludeSelectors : DEFAULT_RESULT_EXCLUDE_SELECTORS,
    loadingSrcIncludes: Array.isArray(action.loadingSrcIncludes) ? action.loadingSrcIncludes : DEFAULT_RESULT_LOADING_SRC_INCLUDES,
    allowLoadingImage: action.allowLoadingImage === true,
    minWidth: action.minWidth,
    minHeight: action.minHeight,
    requireImage: action.requireImage === true,
  });
  ctx.state[key] = {
    createdAtMs: Date.now(),
    signatures: cards.map((card) => card.signature).filter(Boolean),
    timestamps: cards.map((card) => ({ text: card.timestampText, ms: card.timestampMs })),
    count: cards.length,
  };
  return {
    state_key: key,
    count: cards.length,
    latest_timestamp: cards[0] ? cards[0].timestampText : null,
  };
}

function generationAfterMs(ctx, action) {
  if (isFiniteNumber(action.afterMs)) return action.afterMs;
  const key = action.afterTimeStateKey || 'generationTriggeredAtMs';
  const value = ctx.state && ctx.state[key];
  if (isFiniteNumber(value)) return value;
  throw new Error(`generation timestamp missing in ctx.state.${key}; put this action after the real generate click with stopRecordingAfter=true`);
}

function baselineSignatures(ctx, action) {
  const key = action.baselineStateKey || 'resultBaseline';
  const baseline = ctx.state && ctx.state[key];
  return baseline && Array.isArray(baseline.signatures) ? baseline.signatures : [];
}

async function actionWaitForResultAfterTime(ctx, action) {
  const timeout = isFiniteNumber(action.timeout) ? action.timeout : 90000;
  const pollInterval = isFiniteNumber(action.pollInterval) ? action.pollInterval : 1500;
  const afterMs = generationAfterMs(ctx, action);
  const baseline = baselineSignatures(ctx, action);
  const deadline = Date.now() + timeout;
  let attempts = 0;
  while (true) {
    attempts += 1;
    const cards = await scanResultCards(ctx, {
      cardSelector: action.cardSelector || '*',
      imageSelector: action.imageSelector || 'img',
      excludeSelectors: Array.isArray(action.excludeSelectors) ? action.excludeSelectors : DEFAULT_RESULT_EXCLUDE_SELECTORS,
      loadingSrcIncludes: Array.isArray(action.loadingSrcIncludes) ? action.loadingSrcIncludes : DEFAULT_RESULT_LOADING_SRC_INCLUDES,
      allowLoadingImage: action.allowLoadingImage === true,
      minWidth: action.minWidth,
      minHeight: action.minHeight,
      afterMs,
      toleranceMs: action.toleranceMs,
      baselineSignatures: baseline,
      requireImage: action.requireImage === true,
      requireTextIncludes: action.requireTextIncludes,
    });
    if (cards.length) {
      const key = stateKey(action, 'freshResultCard');
      ctx.state[key] = cards[0];
      return {
        state_key: key,
        attempts,
        timestamp_text: cards[0].timestampText,
        timestamp_ms: cards[0].timestampMs,
        generation_triggered_at_ms: afterMs,
        has_image: Boolean(cards[0].image),
        rect: cards[0].rect,
      };
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `wait_for_result_after_time timed out after ${timeout}ms: no new result card timestamped at/after generation click. ` +
        'This usually means the agent did not really click 开始生成, or only historical results are visible.'
      );
    }
    await sleep(pollInterval);
  }
}

async function actionCaptureResultAfterTime(ctx, action) {
  const timeout = isFiniteNumber(action.timeout) ? action.timeout : 120000;
  const pollInterval = isFiniteNumber(action.pollInterval) ? action.pollInterval : 2000;
  const afterMs = generationAfterMs(ctx, action);
  const baseline = baselineSignatures(ctx, action);
  const deadline = Date.now() + timeout;
  let attempts = 0;
  while (true) {
    attempts += 1;
    const cards = await scanResultCards(ctx, {
      cardSelector: action.cardSelector || '*',
      imageSelector: action.imageSelector || 'img',
      excludeSelectors: Array.isArray(action.excludeSelectors) ? action.excludeSelectors : DEFAULT_RESULT_EXCLUDE_SELECTORS,
      loadingSrcIncludes: Array.isArray(action.loadingSrcIncludes) ? action.loadingSrcIncludes : DEFAULT_RESULT_LOADING_SRC_INCLUDES,
      allowLoadingImage: action.allowLoadingImage === true,
      minWidth: action.minWidth,
      minHeight: action.minHeight,
      afterMs,
      toleranceMs: action.toleranceMs,
      baselineSignatures: baseline,
      requireImage: true,
      requireTextIncludes: action.requireTextIncludes,
    });
    if (cards.length && cards[0].image) {
      const card = cards[0];
      const rect = card.image;
      const outputDir = ctx.resultsDir;
      await ensureDir(outputDir);
      if (ctx.overlayConfig) {
        await overlay.highlightElement(ctx.client, rect, action.highlightDuration || 500);
        await sleep(120);
      }
      const clipX = Math.max(0, Math.min(rect.x, ctx.viewport.width - 1));
      const clipY = Math.max(0, Math.min(rect.y, ctx.viewport.height - 1));
      const clip = {
        x: clipX,
        y: clipY,
        width: Math.max(1, Math.min(rect.width, ctx.viewport.width - clipX)),
        height: Math.max(1, Math.min(rect.height, ctx.viewport.height - clipY)),
        scale: 1,
      };
      const result = await ctx.client.send('Page.captureScreenshot', {
        format: action.format || 'png',
        clip,
      });
      const name = action.name || `fresh-result-${Date.now()}`;
      const filePath = path.join(outputDir, `${name}.png`);
      await fsp.writeFile(filePath, Buffer.from(result.data, 'base64'));
      return {
        name,
        path: filePath,
        attempts,
        workflow_step: action.workflowStep || 'result_crop',
        result_asset: true,
        timestamp_text: card.timestampText,
        timestamp_ms: card.timestampMs,
        generation_triggered_at_ms: afterMs,
        matched_src: rect.src || null,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        card_rect: card.rect,
      };
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `capture_result_after_time timed out after ${timeout}ms: no new result image with timestamp >= generation click appeared. ` +
        'Historical result images and loading placeholders such as generate-loading.a5374121.webp are intentionally ignored.'
      );
    }
    await sleep(pollInterval);
  }
}

// ── required form discovery/fill/validation ─────────────────────────────────

async function actionInspectRequiredForm(ctx, action) {
  const key = stateKey(action, 'requiredForm');
  const result = await evaluateRequiredForm(ctx, {
    mode: 'inspect',
    includeOptional: action.includeOptional === true,
    values: action.values || {},
    extraValues: action.extraValues || {},
    generateButtonText: action.generateButtonText || '开始生成',
  });
  if (!result || !Array.isArray(result.fields)) {
    throw new Error('inspect_required_form could not inspect the current form');
  }
  const requiredFields = result.fields.filter((field) => field.required);
  if (action.requireAnyRequired !== false && requiredFields.length === 0) {
    throw new Error('inspect_required_form found no required fields; the page may not be on the intended feature form');
  }
  ctx.state[key] = result;
  return {
    state_key: key,
    field_count: result.fields.length,
    required_count: requiredFields.length,
    required_fields: requiredFields.map((field) => ({
      label: field.label,
      type: field.type,
      filled: field.filled,
      has_value: field.hasValue,
      value: field.value,
    })),
    generate_button: result.generateButton || null,
  };
}

async function actionFillRequiredForm(ctx, action) {
  const key = stateKey(action, 'requiredForm');
  const result = await evaluateRequiredForm(ctx, {
    mode: 'fill',
    includeOptional: action.includeOptional === true,
    values: action.values || {},
    extraValues: action.extraValues || {},
    generateButtonText: action.generateButtonText || '开始生成',
  });
  if (!result || !result.after || !Array.isArray(result.after.fields)) {
    throw new Error('fill_required_form could not fill the current form');
  }
  const failedActions = Array.isArray(result.actions)
    ? result.actions.filter((item) => item.ok === false)
    : [];
  const emptyRequired = Array.isArray(result.emptyRequired) ? result.emptyRequired : [];
  const missingValues = Array.isArray(result.missingValues) ? result.missingValues : [];
  ctx.state[key] = result.after;
  if (missingValues.length) {
    throw new Error(`fill_required_form has no configured values for required fields: ${missingValues.join(', ')}`);
  }
  if (failedActions.length) {
    throw new Error(`fill_required_form failed controls: ${failedActions.map((item) => `${item.label}(${item.reason || 'failed'})`).join(', ')}`);
  }
  if (emptyRequired.length) {
    throw new Error(`fill_required_form left required fields empty: ${emptyRequired.join(', ')}`);
  }
  return {
    state_key: key,
    filled_actions: result.actions,
    required_fields: result.after.fields.filter((field) => field.required).map((field) => ({
      label: field.label,
      type: field.type,
      filled: field.filled,
      value: field.value,
    })),
    generate_button: result.after.generateButton || null,
  };
}

async function actionValidateRequiredForm(ctx, action) {
  const key = stateKey(action, 'requiredForm');
  const result = await evaluateRequiredForm(ctx, {
    mode: 'inspect',
    includeOptional: action.includeOptional === true,
    values: action.values || {},
    extraValues: action.extraValues || {},
    generateButtonText: action.generateButtonText || '开始生成',
  });
  if (!result || !Array.isArray(result.fields)) {
    throw new Error('validate_required_form could not inspect the current form');
  }
  const requiredFields = result.fields.filter((field) => field.required);
  const emptyRequired = requiredFields.filter((field) => !field.filled).map((field) => field.label);
  ctx.state[key] = result;
  if (requiredFields.length === 0 && action.requireAnyRequired !== false) {
    throw new Error('validate_required_form found no required fields; refusing to click generate on an unknown page');
  }
  if (emptyRequired.length) {
    throw new Error(`validate_required_form found empty required fields: ${emptyRequired.join(', ')}`);
  }
  if (action.requireGenerateButton !== false) {
    if (!result.generateButton) {
      throw new Error(`validate_required_form could not find the ${action.generateButtonText || '开始生成'} button`);
    }
    if (result.generateButton.disabled) {
      throw new Error(`validate_required_form found ${action.generateButtonText || '开始生成'} button disabled`);
    }
  }
  return {
    state_key: key,
    required_count: requiredFields.length,
    required_fields: requiredFields.map((field) => ({
      label: field.label,
      type: field.type,
      filled: field.filled,
      value: field.value,
    })),
    generate_button: result.generateButton || null,
  };
}

// ── wait_for_selector ────────────────────────────────────────────────────────

async function actionWaitForSelector(ctx, action) {
  const selector = action.selector;
  if (!selector) throw new Error('wait_for_selector requires "selector"');
  const timeout = isFiniteNumber(action.timeout) ? action.timeout : 60000;
  const pollInterval = isFiniteNumber(action.pollInterval) ? action.pollInterval : 1000;
  const minWidth = isFiniteNumber(action.minWidth) ? action.minWidth : 1;
  const minHeight = isFiniteNumber(action.minHeight) ? action.minHeight : 1;
  const excludeSelectors = Array.isArray(action.excludeSelectors) ? action.excludeSelectors : [];
  const strategy = action.matchStrategy || 'largest';

  const deadline = Date.now() + timeout;
  let attempts = 0;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    attempts += 1;
    const rect = await findElementRect(ctx, selector, { strategy, minWidth, minHeight, excludeSelectors });
    if (rect) {
      return {
        selector,
        found: true,
        attempts,
        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        matched_src: rect.src || null,
      };
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `wait_for_selector timed out after ${timeout}ms without a visible ${minWidth}x${minHeight}+ match: ${selector}. ` +
        'The real generated result never appeared, so nothing downstream should claim a verified result.'
      );
    }
    await sleep(pollInterval);
  }
}

// ── upload_file ──────────────────────────────────────────────────────────────

async function actionUploadFile(ctx, action) {
  const selector = action.selector || 'input[type="file"]';
  const filePath = action.filePath || action.path;
  if (!filePath) throw new Error('upload_file requires "filePath" (a real local image path)');
  const absPath = path.resolve(filePath);
  if (!fs.existsSync(absPath)) {
    throw new Error(`upload_file source not found: ${absPath}. Provide a real product image; empty/fake files cannot generate a result.`);
  }

  await ctx.client.send('DOM.enable', {});
  const evaluated = await ctx.client.send('Runtime.evaluate', {
    expression: `document.querySelector(${JSON.stringify(selector)})`,
  });
  const objectId = evaluated.result && evaluated.result.objectId;
  if (!objectId) {
    throw new Error(`upload_file could not resolve a file input for selector: ${selector}`);
  }
  await ctx.client.send('DOM.setFileInputFiles', { files: [absPath], objectId });
  await ctx.client.send('Runtime.evaluate', {
    expression: `
      (() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (el) {
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
        }
      })()
    `,
  });
  return { selector, file: absPath };
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
  capture_element: actionCaptureElement,
  mark_result_baseline: actionMarkResultBaseline,
  wait_for_result_after_time: actionWaitForResultAfterTime,
  capture_result_after_time: actionCaptureResultAfterTime,
  inspect_required_form: actionInspectRequiredForm,
  fill_required_form: actionFillRequiredForm,
  validate_required_form: actionValidateRequiredForm,
  wait_for_selector: actionWaitForSelector,
  upload_file: actionUploadFile,
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
  requiredFormScript,
  generateButtonClickScript,
};
