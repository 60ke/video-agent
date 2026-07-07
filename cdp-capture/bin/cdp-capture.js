#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { loginProfile } = require('../lib/profile-auth');
const { runTask } = require('../lib/task-runner');
const { verifyAndSave } = require('../lib/verifier');
const { findFfmpeg } = require('../lib/utils');

const ROOT = path.resolve(__dirname, '..');

// ── Help ─────────────────────────────────────────────────────────────────────

const HELP = `
cdp-capture — CDP web page screen capture tool

Usage:
  cdp-capture profile login <profile-id> [options]
  cdp-capture run <task.json> [options]
  cdp-capture verify <output-dir>

Commands:
  profile login   Launch visible Chrome for manual login, save auth_state.json
  run             Execute a capture task from a task JSON file
  verify          Verify video output in an output directory

Options for 'profile login':
  --url <url>           URL to open (default: https://www.kehuanxiongmao.com)
  --port <port>         CDP port (default: 9333)
  --width <px>          Window width (default: 1280)
  --height <px>         Window height (default: 900)

Options for 'run':
  --output <dir>        Override output directory (default: ./output/<task-id>)

Examples:
  cdp-capture profile login myprofile --url https://example.com
  cdp-capture run ./tasks/my-task.json
  cdp-capture verify ./output/task-2026-01-01_00-00-00-000
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
