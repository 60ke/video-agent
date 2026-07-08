'use strict';

/**
 * Navigation Task Builder
 *
 * Generates a complete cdp-capture task JSON from a module id in the registry.
 * The generated task navigates to the module, inspects the form, fills it with
 * demo values, clicks "开始生成", and captures the generated result.
 *
 * Usage:
 *   const { buildTask } = require('./nav-task-builder');
 *   const task = buildTask({ rootDir, moduleId: 'poster', demoValues: {...} });
 *   fs.writeFileSync('my-task.json', JSON.stringify(task, null, 2));
 */

const fs = require('node:fs');
const path = require('node:path');

const { loadModuleRegistry, findModule } = require('./validator');
const { generateButtonClickScript } = require('./actions');

// ── Defaults ─────────────────────────────────────────────────────────────────

const DEFAULT_ORIGIN = 'https://www.kehuanxiongmao.com';
const DEFAULT_PROFILE_ID = 'kehuanxiongmao';
const DEFAULT_VIEWPORT = { width: 1920, height: 1080 };
const DEFAULT_RECORDING = {
  fps: 30,
  jpegQuality: 78,
  videoCodec: 'libx264',
  pixelFormat: 'yuv420p',
  crf: '20',
  preset: 'veryfast',
};
const DEFAULT_CHROME = {
  mode: 'headless',
  port: 9335,
  extraArgs: [],
};
const DEFAULT_OVERLAY = {
  enabled: true,
  cursor: { color: '#ffffff', size: 34, showTrail: true },
  ripple: { color: '#ffd84d', duration: 720 },
  highlight: { color: '#00c6ff', duration: 900 },
};

const MODULE_REGISTRY_RELATIVE = path.join(
  '..',
  'references',
  'site_profiles',
  'kehuanxiongmao_text_to_image_modules.json'
);

// ── Default demo values per module ───────────────────────────────────────────
//
// These are fallback values used when the caller does not supply `demoValues`.
// They are deliberately generic and cover the most common required field labels
// found across modules.  Module-specific overrides are in DEFAULT_DEMO_VALUES.
//
const COMMON_DEMO_VALUES = {
  // Description / prompt fields — matched by label prefix
  '描述': '高清精美的设计效果图，现代简约风格，专业商业用途，细节丰富，色彩搭配和谐。',
  '补充描述': '画面应包含品牌名称、主题文字和装饰元素，整体构图饱满、层次分明。',
  // Aspect ratio / size — matched by label prefix
  '图片比例': '竖版',
  '海报尺寸': '竖版',
  '尺寸': '竖版',
  // Quality
  '图片质量': '普通：速度快、费用低，小文字有乱码概率',
  // Common module-specific label patterns
  '主题': '商业场景设计',
  '名称': '示例品牌',
};

const MODULE_SPECIFIC_DEMO_VALUES = {
  poster: {
    '海报描述': '夏日咖啡新品上市海报，主标题：冰萃拿铁上新，副标题：清爽一夏限时尝鲜，画面包含冰咖啡杯、柠檬片、蓝橙撞色背景和醒目的促销信息。',
    '海报主题': '夏日咖啡新品上市',
    '主题描述': '夏日咖啡新品上市海报，主标题：冰萃拿铁上新，副标题：清爽一夏限时尝鲜，画面包含冰咖啡杯、柠檬片、蓝橙撞色背景和醒目的促销信息。',
  },
  ecommerce: {
    '商品描述': '高端无线蓝牙耳机，白色简约设计，产品图展示正面和侧面角度，背景为浅灰色渐变。',
    '商品名称': '无线蓝牙耳机',
    '商品主图': '高端无线蓝牙耳机，白色简约设计',
  },
  signboard: {
    '招牌描述': '咖啡店门头招牌设计，木质质感背景，暖色调灯光，品牌名称：COFFEE HOUSE，现代简约风格。',
    '店铺名称': 'COFFEE HOUSE',
  },
  logo: {
    'LOGO描述': '科技公司品牌LOGO，蓝色为主色调，简洁几何图形，体现创新和科技感。',
    '品牌名称': 'TECHVISION',
    'LOGO名称': 'TECHVISION',
  },
  ip: {
    'IP描述': '可爱卡通熊猫IP形象设计，圆润造型，黑白配色，身穿蓝色围裙，手持画笔，展现创意和艺术感。',
    'IP名称': '创意熊猫',
  },
  culture_wall: {
    '文化墙描述': '企业文化墙设计，展示公司发展历程和核心价值观，蓝绿色调，现代简约风格，包含时间轴和图形元素。',
    '主题描述': '企业文化墙——创新、协作、共赢',
  },
  activity_decoration: {
    '活动描述': '商场春节活动美陈设计，红色金色为主色调，包含灯笼、福字、生肖元素，营造喜庆节日氛围。',
    '活动主题': '新春嘉年华',
  },
  main_kv: {
    '物料类型': '展架',
    '行业': '餐饮美食',
    '主标题': '新春大促销 限时特惠',
    '副标题': '全场菜品满100减30',
    '尺寸比例': '竖版',
  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Resolve demo values for a module: merge common + module-specific + caller overrides.
 */
function resolveDemoValues(moduleId, callerValues) {
  const specific = MODULE_SPECIFIC_DEMO_VALUES[moduleId] || {};
  return { ...COMMON_DEMO_VALUES, ...specific, ...(callerValues || {}) };
}

/**
 * Build the menu navigation script: click 文生图, then click the module label.
 * This produces the visible navigation path for video evidence.
 */
function buildMenuNavigationScript(moduleLabel) {
  // Click 文生图 in the sidebar
  const clickNavScript = `(() => { const els = [...document.querySelectorAll('*')]; const target = els.find(el => el.children.length === 0 && el.textContent.trim() === '文生图'); if (target) { target.click(); return 'clicked 文生图'; } const link = [...document.querySelectorAll('a,span,div,li')].find(el => el.textContent.trim() === '文生图' && el.offsetParent !== null); if (link) { link.click(); return 'clicked 文生图 via link'; } return '文生图 not found'; })()`;

  // Click the module label in the hover submenu
  const clickModuleScript = `(() => { const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim(); const candidates = [...document.querySelectorAll('a,span,div,li,p,h1,h2,h3,h4,button')].filter(el => el.offsetParent !== null && normalize(el.textContent) === ${JSON.stringify(moduleLabel)}); const target = candidates.sort((a, b) => a.getBoundingClientRect().width * a.getBoundingClientRect().height - b.getBoundingClientRect().width * b.getBoundingClientRect().height)[0]; if (target) { target.click(); return 'clicked ${moduleLabel}'; } return '${moduleLabel} not found'; })()`;

  return { clickNavScript, clickModuleScript };
}

// ── Main builder ─────────────────────────────────────────────────────────────

/**
 * Build a complete task JSON for a module.
 *
 * @param {object} options
 * @param {string} options.rootDir        - cdp-capture root directory
 * @param {string} options.moduleId       - module id, alias, or label
 * @param {object} [options.demoValues]   - override demo field values
 * @param {string} [options.profileId]    - Chrome profile id
 * @param {object} [options.viewport]     - { width, height }
 * @param {object} [options.recording]    - recording config overrides
 * @param {object} [options.chrome]       - chrome config overrides
 * @param {string} [options.outputDir]    - output directory override
 * @param {boolean} [options.directNavigation] - skip menu clicks, navigate directly (default false)
 * @param {number} [options.resultTimeoutMs]  - max wait for result (default 180000)
 * @param {string} [options.taskName]     - optional task name for identification
 * @returns {object} task JSON ready for cdp-capture run
 */
function buildTask(options) {
  const rootDir = options.rootDir;
  const registry = loadModuleRegistry(rootDir);
  const mod = findModule(registry, options.moduleId);

  if (!mod) {
    throw new Error(
      `Module not found: "${options.moduleId}". Available: ${(registry.modules || [])
        .map((m) => m.id)
        .join(', ')}`
    );
  }

  const origin =
    (registry.cdp_navigation_contract &&
      registry.cdp_navigation_contract.canonical_origin) ||
    DEFAULT_ORIGIN;

  const demoValues = resolveDemoValues(mod.id, options.demoValues);
  const stateKey = `${mod.id}_required_form`;
  const baselineKey = `${mod.id}_result_baseline`;
  const resultCardKey = `${mod.id}_fresh_card`;
  const resultTimeoutMs = options.resultTimeoutMs || 180000;

  // ── Build actions array ──────────────────────────────────────────────────

  const actions = [];

  if (options.directNavigation) {
    // Navigate directly to the module URL for speed (no menu video evidence)
    actions.push({
      type: 'wait',
      duration: 2000,
      narration: `打开${mod.label}页面`,
    });
    actions.push({
      type: 'screenshot',
      name: 'page_entry',
    });
  } else {
    // Full menu navigation for video evidence: 文生图 → module label
    const { clickNavScript, clickModuleScript } = buildMenuNavigationScript(mod.label);

    actions.push({
      type: 'wait',
      duration: 2000,
      narration: '打开柯幻熊猫首页',
    });
    actions.push({
      type: 'screenshot',
      name: 'home_entry',
    });
    actions.push({
      type: 'evaluate_js',
      script: clickNavScript,
      narration: '进入文生图模块',
      cameraFocus: 'left_nav',
      required: true,
      expectIncludes: 'clicked',
    });
    actions.push({
      type: 'wait',
      duration: 1500,
    });
    actions.push({
      type: 'evaluate_js',
      script: clickModuleScript,
      narration: `选择${mod.label}功能`,
      cameraFocus: 'feature_menu',
      required: true,
      expectIncludes: 'clicked',
    });
    actions.push({
      type: 'wait',
      duration: 2500,
    });
    actions.push({
      type: 'screenshot',
      name: 'feature_page_empty',
    });
  }

  // Inspect required form
  actions.push({
    type: 'inspect_required_form',
    stateKey,
    includeOptional: true,
    cameraFocus: 'left_form',
    required: true,
  });

  // Fill required form with demo values
  actions.push({
    type: 'fill_required_form',
    stateKey,
    includeOptional: true,
    values: demoValues,
    narration: `填写${mod.label}表单`,
    cameraFocus: 'left_form',
    required: true,
  });

  // Validate required form
  actions.push({
    type: 'validate_required_form',
    stateKey,
    includeOptional: true,
    generateButtonText: '开始生成',
    requireGenerateButton: true,
    cameraFocus: 'generate_button',
    required: true,
  });

  // Confirm form content
  actions.push({
    type: 'wait',
    duration: 1500,
    narration: '确认表单内容',
  });
  actions.push({
    type: 'screenshot',
    name: 'form_filled',
    workflowStep: 'form_filled',
  });

  // Mark result baseline
  actions.push({
    type: 'mark_result_baseline',
    cardSelector: '*',
    imageSelector: 'img',
    stateKey: baselineKey,
    minWidth: 240,
    minHeight: 240,
    required: true,
  });

  // Click generate button (uses generateButtonClickScript from actions.js)
  actions.push({
    type: 'evaluate_js',
    script: generateButtonClickScript({ buttonText: '开始生成' }),
    narration: '点击开始生成',
    cameraFocus: 'generate_button',
    required: true,
    emphasis: 'generate',
    stopRecordingAfter: true,
    expectIncludes: 'clicked',
    failIfIncludes: 'disabled',
  });

  // Wait for fresh result card to appear
  actions.push({
    type: 'wait_for_result_after_time',
    cardSelector: '*',
    imageSelector: 'img',
    baselineStateKey: baselineKey,
    afterTimeStateKey: 'generationTriggeredAtSecondMs',
    toleranceMs: 0,
    stateKey: resultCardKey,
    timeout: 45000,
    pollInterval: 1500,
    minWidth: 240,
    minHeight: 240,
    required: true,
    narration: `等待本次${mod.label}任务出现`,
  });

  // Screenshot generating state
  actions.push({
    type: 'screenshot',
    name: 'generating_state',
    workflowStep: 'generating',
  });

  // Screenshot result page
  actions.push({
    type: 'screenshot',
    name: 'result_page',
    workflowStep: 'result_page',
  });

  // Capture result image
  actions.push({
    type: 'capture_result_after_time',
    cardSelector: '*',
    imageSelector: 'img',
    name: `real_${mod.id}_result`,
    workflowStep: 'result_crop',
    resultAsset: true,
    required: true,
    cameraFocus: 'result_area',
    baselineStateKey: baselineKey,
    afterTimeStateKey: 'generationTriggeredAtSecondMs',
    toleranceMs: 0,
    timeout: resultTimeoutMs,
    pollInterval: 30000,
    loadingSrcIncludes: [
      'generate-loading.a5374121.webp',
      '/static/img/generate-loading',
    ],
    minWidth: 240,
    minHeight: 240,
  });

  // ── Assemble task JSON ───────────────────────────────────────────────────

  const task = {
    profileId: options.profileId || DEFAULT_PROFILE_ID,
    url: options.directNavigation ? origin + mod.route : origin,
    viewport: { ...DEFAULT_VIEWPORT, ...(options.viewport || {}) },
    recording: { ...DEFAULT_RECORDING, ...(options.recording || {}) },
    chrome: { ...DEFAULT_CHROME, ...(options.chrome || {}) },
    overlay: DEFAULT_OVERLAY,
    actions,
    outputDir: options.outputDir || undefined,
    // Metadata for identification
    _meta: {
      taskName: options.taskName || `auto_${mod.id}`,
      moduleId: mod.id,
      moduleLabel: mod.label,
      moduleRoute: mod.route,
      sourceType: mod.source_type,
      primaryTaskType: mod.primary_task_type,
      generatedAt: new Date().toISOString(),
      generator: 'nav-task-builder',
    },
  };

  // Remove undefined outputDir
  if (!task.outputDir) delete task.outputDir;

  return task;
}

/**
 * List all available module ids and labels from the registry.
 * @param {string} rootDir - cdp-capture root directory
 * @returns {Array<{id, label, route, aliases}>}
 */
function listModules(rootDir) {
  const registry = loadModuleRegistry(rootDir);
  return (registry.modules || []).map((m) => ({
    id: m.id,
    label: m.label,
    route: m.route,
    aliases: m.aliases || [],
  }));
}

module.exports = {
  buildTask,
  listModules,
  resolveDemoValues,
};
