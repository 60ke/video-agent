'use strict';

function requiredFormScript(options = {}) {
  const mode = options.mode || 'inspect';
  const includeOptional = options.includeOptional === true;
  const generateButtonText = options.generateButtonText || '开始生成';
  return `
    (() => {
      const mode = ${JSON.stringify(mode)};
      const includeOptional = ${JSON.stringify(includeOptional)};
      const generateButtonText = ${JSON.stringify(generateButtonText)};
      const normalize = (value) => String(value || '')
        .replace(/[\\u00a0\\s]+/g, ' ')
        .replace(/[＊*]/g, '')
        .trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) !== 0 && r.width > 0 && r.height > 0 &&
          r.bottom > 0 && r.right > 0 && r.top < window.innerHeight && r.left < window.innerWidth;
      };
      const rectOf = (el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
      };
      const isRedRequiredMark = (el) => {
        const color = window.getComputedStyle(el).color || '';
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
        if (!required && !includeOptional) continue;
        const key = label + '|' + Math.round(container.getBoundingClientRect().top);
        if (seen.has(key)) continue;
        seen.add(key);
        const control = detectControl(container);
        const value = control.value || '';
        const placeholder = control.el && (control.el.getAttribute('placeholder') || control.el.getAttribute('aria-placeholder') || '');
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
      return {
        mode,
        fields,
        generateButton: generateButton ? { disabled: buttonDisabled, rect: rectOf(generateButton), text: normalize(generateButton.textContent) } : null,
      };
    })()
  `;
}

module.exports = {
  requiredFormScript,
};
