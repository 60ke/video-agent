'use strict';

/**
 * Lightweight CDP Navigation Validator
 *
 * Launches Chrome (reusing chrome-launcher + profile-auth), navigates to a
 * module URL, and runs a battery of assertions defined in the module registry.
 * Does NOT record video or execute the full task-runner pipeline — it only
 * checks that the page is reachable, the form is present, and the generate
 * button exists.
 *
 * Output: a structured JSON report written to stdout and optionally saved
 * to a file.
 */

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const { launchChrome, closeChrome } = require('./chrome-launcher');
const { restoreAuthState, getProfileDir, getAuthStatePath } = require('./profile-auth');
const { requiredFormScript } = require('./actions');
const { sleep, ensureDir } = require('./utils');

// ── Defaults ─────────────────────────────────────────────────────────────────

const DEFAULT_ORIGIN = 'https://www.kehuanxiongmao.com';
const DEFAULT_PROFILE_ID = 'kehuanxiongmao';
const DEFAULT_VIEWPORT = { width: 1920, height: 1080 };
const DEFAULT_CHROME_PORT = 9340;
const MODULE_REGISTRY_RELATIVE = path.join(
  '..',
  'references',
  'site_profiles',
  'kehuanxiongmao_text_to_image_modules.json'
);

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Load the module registry JSON.
 * @param {string} cdpCaptureRoot  - cdp-capture root directory
 * @returns {object} parsed registry
 */
function loadModuleRegistry(cdpCaptureRoot) {
  const registryPath = path.resolve(cdpCaptureRoot, MODULE_REGISTRY_RELATIVE);
  if (!fs.existsSync(registryPath)) {
    throw new Error(`Module registry not found: ${registryPath}`);
  }
  return JSON.parse(fs.readFileSync(registryPath, 'utf8'));
}

/**
 * Find a module by id, alias, or label (case-insensitive).
 * @param {object} registry
 * @param {string} moduleIdOrAlias
 * @returns {object|null} module definition
 */
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

/**
 * Wait for a Page.loadEventFired event with a timeout.
 * @param {object} client  - CDP client
 * @param {number} timeoutMs
 * @returns {Promise<boolean>} true if loaded within timeout
 */
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

/**
 * Evaluate a JS expression in the page and return the result value.
 * @param {object} client
 * @param {string} expression
 * @returns {Promise<any>}
 */
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

/**
 * Take a screenshot and save it to a file.
 * @param {object} client
 * @param {string} filepath
 * @returns {Promise<void>}
 */
async function takeScreenshot(client, filepath) {
  const { data } = await client.send('Page.captureScreenshot', {
    format: 'jpeg',
    quality: 80,
  });
  await fsp.writeFile(filepath, Buffer.from(data, 'base64'));
}

// ── Assertion helpers ────────────────────────────────────────────────────────

/**
 * Assertion: the current pathname matches the module route.
 * @param {object} client
 * @param {object} mod
 * @returns {Promise<object>} { pass, actual, expected, message }
 */
async function assertRoute(client, mod) {
  const pathname = await evaluate(client, 'window.location.pathname');
  const expected = mod.route;
  const pass = pathname === expected;
  return {
    name: 'route',
    pass,
    actual: pathname,
    expected,
    message: pass
      ? `Route matches: ${pathname}`
      : `Route mismatch: expected "${expected}", got "${pathname}"`,
  };
}

/**
 * Assertion: the .label-active element exists and its text matches page_title.
 * @param {object} client
 * @param {object} mod
 * @returns {Promise<object>}
 */
async function assertPageTitle(client, mod) {
  const result = await evaluate(
    client,
    `(() => {
      const el = document.querySelector('.label-active');
      if (!el) return { found: false, text: '' };
      const text = (el.textContent || '').replace(/\\s+/g, ' ').trim();
      return { found: true, text };
    })()`
  );
  const found = result && result.found;
  const text = result ? result.text : '';
  const pass = found && text === mod.page_title;
  return {
    name: 'page_title',
    pass,
    actual: text,
    expected: mod.page_title,
    message: pass
      ? `Page title matches: ${text}`
      : found
        ? `Page title mismatch: expected "${mod.page_title}", got "${text}"`
        : '.label-active element not found on page',
  };
}

/**
 * Assertion: the page contains a visible "开始生成" button.
 * @param {object} client
 * @returns {Promise<object>}
 */
async function assertGenerateButton(client) {
  const result = await evaluate(
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
      const candidates = [...document.querySelectorAll('button, [role="button"], a, div, span')]
        .filter((el) => visible(el) &&
          normalize(el.textContent).includes('开始生成') &&
          normalize(el.textContent).length <= 20);
      if (candidates.length === 0) return { found: false, disabled: false };
      const btn = candidates[0].closest('button') || candidates[0];
      const disabled = Boolean(btn.disabled ||
        btn.getAttribute('aria-disabled') === 'true' ||
        /disabled|is-disabled/.test(String(btn.className)));
      return { found: true, disabled };
    })()`
  );
  const found = result && result.found;
  const disabled = result ? result.disabled : false;
  const pass = found && !disabled;
  return {
    name: 'generate_button',
    pass,
    actual: found ? (disabled ? 'disabled' : 'enabled') : 'not found',
    expected: 'enabled',
    message: pass
      ? 'Generate button "开始生成" found and enabled'
      : found
        ? `Generate button "开始生成" found but disabled`
        : 'Generate button "开始生成" not found',
  };
}

/**
 * Assertion: the left sidebar contains visible text "文生图" (auth check proxy).
 * If the text is absent the user is likely on a login redirect.
 * @param {object} client
 * @returns {Promise<object>}
 */
async function assertAuthState(client) {
  const result = await evaluate(
    client,
    `(() => {
      const normalize = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
      const els = [...document.querySelectorAll('a, span, div, li, p, h1, h2, h3, h4')];
      const target = els.find((el) => {
        if (!el.offsetParent && el.tagName !== 'BODY') return false;
        return normalize(el.textContent) === '文生图';
      });
      return { found: Boolean(target) };
    })()`
  );
  const found = result && result.found;
  return {
    name: 'auth_state',
    pass: found,
    actual: found ? 'logged in' : 'not logged in (文生图 nav missing)',
    expected: 'logged in',
    message: found
      ? 'Auth state OK: 文生图 nav visible'
      : 'Auth state FAIL: 文生图 nav text not found — user may be on login page',
  };
}

/**
 * Assertion: inspect the form and report required fields.
 * @param {object} client
 * @returns {Promise<object>}
 */
async function assertFormStructure(client) {
  const script = requiredFormScript({ mode: 'inspect', includeOptional: true });
  const result = await evaluate(client, script);
  if (!result || !Array.isArray(result.fields)) {
    return {
      name: 'form_structure',
      pass: false,
      actual: 'no form found',
      expected: 'form with required fields',
      message: 'Form inspection failed: no fields array returned',
      details: null,
    };
  }
  const requiredFields = result.fields.filter((f) => f.required);
  const pass = requiredFields.length > 0;
  return {
    name: 'form_structure',
    pass,
    actual: `${result.fields.length} fields (${requiredFields.length} required)`,
    expected: 'at least 1 required field',
    message: pass
      ? `Form OK: ${result.fields.length} fields, ${requiredFields.length} required`
      : 'Form inspection found no required fields — page may not be on the intended feature form',
    details: {
      total_fields: result.fields.length,
      required_count: requiredFields.length,
      required_fields: requiredFields.map((f) => ({
        label: f.label,
        type: f.type,
        filled: f.filled,
      })),
      generate_button: result.generateButton || null,
    },
  };
}

// ── Main validator ───────────────────────────────────────────────────────────

/**
 * Validate one or more modules.
 *
 * @param {object} options
 * @param {string} options.rootDir        - cdp-capture root directory
 * @param {string|string[]} options.modules - module id(s) / alias(es) to validate; '*' for all
 * @param {string} [options.profileId]    - Chrome profile id (default 'kehuanxiongmao')
 * @param {number} [options.port]         - Chrome debugging port (default 9340)
 * @param {string} [options.mode]         - 'headless' | 'visible' (default 'headless')
 * @param {number} [options.width]        - viewport width (default 1920)
 * @param {number} [options.height]       - viewport height (default 1080)
 * @param {string} [options.outputDir]    - directory to save report + screenshots
 * @param {boolean} [options.screenshot]  - save screenshots per module (default true)
 * @param {boolean} [options.inspectForm] - run form inspection (default true)
 * @returns {Promise<object>} validation report
 */
async function validateModules(options) {
  const rootDir = options.rootDir;
  const registry = loadModuleRegistry(rootDir);
  const profileId = options.profileId || DEFAULT_PROFILE_ID;
  const port = options.port || DEFAULT_CHROME_PORT;
  const mode = options.mode || 'headless';
  const width = options.width || DEFAULT_VIEWPORT.width;
  const height = options.height || DEFAULT_VIEWPORT.height;
  const origin = (registry.cdp_navigation_contract &&
    registry.cdp_navigation_contract.canonical_origin) ||
    DEFAULT_ORIGIN;

  // Resolve modules to validate
  let moduleIds = options.modules;
  if (typeof moduleIds === 'string') {
    moduleIds = moduleIds === '*' ? 'all' : [moduleIds];
  }
  if (moduleIds === 'all' || (Array.isArray(moduleIds) && moduleIds.includes('*'))) {
    moduleIds = (registry.modules || []).map((m) => m.id);
  }
  if (!Array.isArray(moduleIds) || moduleIds.length === 0) {
    throw new Error('No modules specified for validation');
  }

  // Resolve module definitions
  const modulesToValidate = [];
  const notFound = [];
  for (const id of moduleIds) {
    const mod = findModule(registry, id);
    if (mod) {
      modulesToValidate.push(mod);
    } else {
      notFound.push(id);
    }
  }

  // Output directory
  const outputDir = options.outputDir
    ? path.resolve(options.outputDir)
    : path.join(rootDir, 'output', 'validation');
  await ensureDir(outputDir);

  const report = {
    timestamp: new Date().toISOString(),
    profile_id: profileId,
    origin,
    total: modulesToValidate.length,
    passed: 0,
    failed: 0,
    results: [],
    not_found: notFound,
  };

  if (notFound.length > 0) {
    process.stderr.write(`⚠ Unknown module ids: ${notFound.join(', ')}\n`);
  }

  if (modulesToValidate.length === 0) {
    return report;
  }

  // Launch Chrome once for all modules
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

    // Restore auth state (cookies) before any navigation
    const authResult = await restoreAuthState(client, {
      rootDir,
      profileId,
      targetUrl: origin,
      log: (msg) => process.stderr.write(`  ${msg}\n`),
    });

    if (!authResult.authState) {
      process.stderr.write(
        `⚠ No auth_state.json at ${authStatePath}; validation will likely fail on auth assertions\n`
      );
    }

    // Validate each module
    for (let i = 0; i < modulesToValidate.length; i++) {
      const mod = modulesToValidate[i];
      const moduleUrl = origin + mod.route;
      process.stderr.write(
        `\n[${i + 1}/${modulesToValidate.length}] Validating: ${mod.id} (${mod.label}) → ${moduleUrl}\n`
      );

      const moduleResult = {
        module_id: mod.id,
        label: mod.label,
        route: mod.route,
        url: moduleUrl,
        assertions: [],
        pass: false,
      };

      try {
        // Navigate to the module URL
        const loadPromise = waitForLoadEvent(client, 30000);
        await client.send('Page.navigate', { url: moduleUrl });
        const loaded = await loadPromise;
        process.stderr.write(`  Page loaded: ${loaded}\n`);

        // Restore storage after navigation
        if (typeof authResult.storageRestored === 'function') {
          await authResult.storageRestored();
        }

        // Give SPA router a moment to settle
        await sleep(2000);

        // Run assertions
        const assertions = [];

        // 1. Auth state
        assertions.push(await assertAuthState(client));

        // 2. Route match
        assertions.push(await assertRoute(client, mod));

        // 3. Page title
        assertions.push(await assertPageTitle(client, mod));

        // 4. Generate button
        assertions.push(await assertGenerateButton(client));

        // 5. Form structure
        if (options.inspectForm !== false) {
          assertions.push(await assertFormStructure(client));
        }

        // Screenshot
        if (options.screenshot !== false) {
          const screenshotPath = path.join(outputDir, `validate_${mod.id}.jpg`);
          try {
            await takeScreenshot(client, screenshotPath);
            moduleResult.screenshot = screenshotPath;
            process.stderr.write(`  Screenshot: ${screenshotPath}\n`);
          } catch (e) {
            process.stderr.write(`  Screenshot failed: ${e.message}\n`);
          }
        }

        moduleResult.assertions = assertions;
        moduleResult.pass = assertions.every((a) => a.pass);
      } catch (err) {
        process.stderr.write(`  ✗ Error: ${err.message}\n`);
        moduleResult.assertions.push({
          name: 'exception',
          pass: false,
          actual: err.message,
          expected: 'no exception',
          message: `Validation threw: ${err.message}`,
        });
        moduleResult.pass = false;
      }

      report.results.push(moduleResult);
      if (moduleResult.pass) {
        report.passed++;
      } else {
        report.failed++;
      }

      // Print assertion summary
      for (const a of moduleResult.assertions) {
        const icon = a.pass ? '✓' : '✗';
        process.stderr.write(`  ${icon} ${a.name}: ${a.message}\n`);
      }
    }
  } finally {
    if (chromeHandle) {
      process.stderr.write('\nClosing Chrome...\n');
      await closeChrome(chromeHandle);
    }
  }

  // Save report
  const reportPath = path.join(outputDir, 'validation_report.json');
  await fsp.writeFile(reportPath, JSON.stringify(report, null, 2), 'utf8');
  process.stderr.write(`\nReport saved: ${reportPath}\n`);
  process.stderr.write(
    `Summary: ${report.passed}/${report.total} passed, ${report.failed} failed\n`
  );

  return report;
}

module.exports = {
  validateModules,
  loadModuleRegistry,
  findModule,
};
