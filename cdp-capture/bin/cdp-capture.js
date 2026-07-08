#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { loginProfile } = require('../lib/profile-auth');
const { runTask } = require('../lib/task-runner');
const { verifyAndSave } = require('../lib/verifier');
const { findFfmpeg } = require('../lib/utils');
const { validateModules, loadModuleRegistry } = require('../lib/validator');
const { buildTask, listModules } = require('../lib/nav-task-builder');

const ROOT = path.resolve(__dirname, '..');

// ── Help ─────────────────────────────────────────────────────────────────────

const HELP = `
cdp-capture — CDP web page screen capture tool

Usage:
  cdp-capture profile login <profile-id> [options]
  cdp-capture run <task.json> [options]
  cdp-capture verify <output-dir>
  cdp-capture validate <module-id|*> [options]
  cdp-capture generate-task <module-id> [options]
  cdp-capture list-modules

Commands:
  profile login    Launch visible Chrome for manual login, save auth_state.json
  run              Execute a capture task from a task JSON file
  verify           Verify video output in an output directory
  validate         Validate module navigation, auth state, and form structure
  generate-task    Generate a task JSON for a module from the registry
  list-modules     List all available modules from the registry

Options for 'profile login':
  --url <url>           URL to open (default: https://www.kehuanxiongmao.com)
  --port <port>         CDP port (default: 9333)
  --width <px>          Window width (default: 1280)
  --height <px>         Window height (default: 900)

Options for 'run':
  --output <dir>        Override output directory (default: ./output/<task-id>)

Options for 'validate':
  --profile <id>        Chrome profile id (default: kehuanxiongmao)
  --port <port>         CDP port (default: 9340)
  --mode <mode>         'headless' or 'visible' (default: headless)
  --width <px>          Viewport width (default: 1920)
  --height <px>         Viewport height (default: 1080)
  --output <dir>        Output directory for report + screenshots
  --no-form             Skip form structure inspection
  --no-screenshot       Skip screenshots

Options for 'generate-task':
  --output <file>       Write task JSON to file (default: stdout)
  --direct              Navigate directly to module URL (skip menu clicks)
  --profile <id>        Chrome profile id (default: kehuanxiongmao)
  --demo-json <file>    JSON file with demo field value overrides
  --result-timeout <ms> Max wait for result (default: 180000)
  --task-name <name>    Task name for identification

Examples:
  cdp-capture profile login myprofile --url https://example.com
  cdp-capture run ./tasks/my-task.json
  cdp-capture verify ./output/task-2026-01-01_00-00-00-000
  cdp-capture validate poster
  cdp-capture validate '*' --mode visible
  cdp-capture generate-task poster --output ./tasks/poster.json
  cdp-capture generate-task ecommerce --direct --demo-json ./demo.json
  cdp-capture list-modules
`;

// ── Parse args ───────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const args = { _: [], options: {} };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith('--')) {
        args.options[key] = next;
        i++;
      } else {
        args.options[key] = true;
      }
    } else {
      args._.push(arg);
    }
  }
  return args;
}

// ── Commands ─────────────────────────────────────────────────────────────────

async function cmdProfileLogin(args) {
  const profileId = args._[0] || 'default';
  const url = args.options.url || 'https://www.kehuanxiongmao.com';
  const port = parseInt(args.options.port || '9333', 10);
  const width = parseInt(args.options.width || '1280', 10);
  const height = parseInt(args.options.height || '900', 10);

  await loginProfile({
    rootDir: ROOT,
    profileId,
    url,
    port,
    width,
    height,
  });
}

async function cmdRun(args) {
  const taskFile = args._[0];
  if (!taskFile) {
    console.error('Error: task JSON file path is required');
    console.error('Usage: cdp-capture run <task.json>');
    process.exit(1);
  }

  const taskPath = path.resolve(taskFile);
  if (!fs.existsSync(taskPath)) {
    console.error(`Error: task file not found: ${taskPath}`);
    process.exit(1);
  }

  const task = JSON.parse(await fsp.readFile(taskPath, 'utf8'));

  // Override output dir if specified
  if (args.options.output) {
    task.outputDir = path.resolve(args.options.output);
  }

  const result = await runTask(task, ROOT);
  // Final summary to stderr (stdout is reserved for NDJSON events)
  console.error(`\n✓ Task completed: ${result.taskId}`);
  console.error(`  Video: ${result.videoPath}`);
  console.error(`  Output: ${result.outputDir}`);
  console.error(`  Verify: ${result.verify.allChecksPassed ? 'PASS' : 'FAIL'}`);
}

async function cmdVerify(args) {
  const outputDir = args._[0];
  if (!outputDir) {
    console.error('Error: output directory is required');
    console.error('Usage: cdp-capture verify <output-dir>');
    process.exit(1);
  }

  const resolvedDir = path.resolve(outputDir);
  const videoPath = path.join(resolvedDir, 'video.mp4');

  // Try to read expected values from metadata.json
  let expected = {};
  const metadataPath = path.join(resolvedDir, 'metadata.json');
  if (fs.existsSync(metadataPath)) {
    const meta = JSON.parse(await fsp.readFile(metadataPath, 'utf8'));
    const [w, h] = (meta.resolution || '').split('x').map(Number);
    expected = { width: w, height: h, fps: meta.fps };
  }

  const ffmpegPath = findFfmpeg();
  const result = await verifyAndSave(videoPath, ffmpegPath, resolvedDir, expected);

  console.log(JSON.stringify(result, null, 2));
  if (!result.allChecksPassed) {
    process.exitCode = 1;
  }
}

async function cmdValidate(args) {
  const moduleId = args._[0];
  if (!moduleId) {
    console.error('Error: module id is required');
    console.error('Usage: cdp-capture validate <module-id|*> [options]');
    console.error('  Use * to validate all modules');
    process.exit(1);
  }

  const report = await validateModules({
    rootDir: ROOT,
    modules: moduleId,
    profileId: args.options.profile || 'kehuanxiongmao',
    port: parseInt(args.options.port || '9340', 10),
    mode: args.options.mode || 'headless',
    width: parseInt(args.options.width || '1920', 10),
    height: parseInt(args.options.height || '1080', 10),
    outputDir: args.options.output ? path.resolve(args.options.output) : undefined,
    inspectForm: args.options['no-form'] !== true,
    screenshot: args.options['no-screenshot'] !== true,
  });

  // Print report to stdout as JSON
  console.log(JSON.stringify(report, null, 2));

  if (report.failed > 0) {
    process.exitCode = 1;
  }
}

async function cmdGenerateTask(args) {
  const moduleId = args._[0];
  if (!moduleId) {
    console.error('Error: module id is required');
    console.error('Usage: cdp-capture generate-task <module-id> [options]');
    console.error('  Available modules: cdp-capture list-modules');
    process.exit(1);
  }

  // Load demo values from file if specified
  let demoValues = {};
  if (args.options['demo-json']) {
    const demoPath = path.resolve(args.options['demo-json']);
    if (!fs.existsSync(demoPath)) {
      console.error(`Error: demo JSON file not found: ${demoPath}`);
      process.exit(1);
    }
    demoValues = JSON.parse(await fsp.readFile(demoPath, 'utf8'));
  }

  const task = buildTask({
    rootDir: ROOT,
    moduleId,
    demoValues,
    profileId: args.options.profile || undefined,
    directNavigation: args.options.direct === true,
    resultTimeoutMs: args.options['result-timeout']
      ? parseInt(args.options['result-timeout'], 10)
      : undefined,
    taskName: args.options['task-name'] || undefined,
    outputDir: args.options.outputDir || undefined,
  });

  const json = JSON.stringify(task, null, 2);

  if (args.options.output) {
    const outputPath = path.resolve(args.options.output);
    const outputDir = path.dirname(outputPath);
    if (!fs.existsSync(outputDir)) {
      await fsp.mkdir(outputDir, { recursive: true });
    }
    await fsp.writeFile(outputPath, json, 'utf8');
    console.error(`Task JSON written: ${outputPath}`);
  } else {
    console.log(json);
  }
}

async function cmdListModules() {
  const modules = listModules(ROOT);
  console.log('Available modules:');
  for (const mod of modules) {
    const aliases = mod.aliases.length > 0 ? ` (aliases: ${mod.aliases.join(', ')})` : '';
    console.log(`  ${mod.id.padEnd(20)} ${mod.label.padEnd(10)} ${mod.route}${aliases}`);
  }
  console.log(`\nTotal: ${modules.length} modules`);
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const argv = process.argv.slice(2);

  if (argv.length === 0 || argv[0] === '--help' || argv[0] === '-h') {
    console.log(HELP);
    return;
  }

  const command = argv[0];
  const args = parseArgs(argv.slice(1));

  try {
    switch (command) {
      case 'profile':
        if (args._[0] === 'login') {
          args._.shift();
          await cmdProfileLogin(args);
        } else {
          console.error('Unknown profile subcommand. Use: profile login');
          process.exit(1);
        }
        break;
      case 'run':
        await cmdRun(args);
        break;
      case 'verify':
        await cmdVerify(args);
        break;
      case 'validate':
        await cmdValidate(args);
        break;
      case 'generate-task':
        await cmdGenerateTask(args);
        break;
      case 'list-modules':
        await cmdListModules();
        break;
      default:
        console.error(`Unknown command: ${command}`);
        console.log(HELP);
        process.exit(1);
    }
  } catch (err) {
    console.error(`\n✗ Error: ${err.message}`);
    if (process.env.DEBUG) {
      console.error(err.stack);
    }
    process.exit(1);
  }
}

main();
