#!/usr/bin/env node
'use strict';

const path = require('node:path');
const { loginProfile } = require('../lib/profile-auth');
const { captureMaterials } = require('../lib/material-capture');

const ROOT = path.resolve(__dirname, '..');

// ── Help ─────────────────────────────────────────────────────────────────────

const HELP = `
cdp-capture — CDP web page screen capture tool

Usage:
  cdp-capture profile login <profile-id> [options]
  cdp-capture capture-material <module-id|*> [options]

Commands:
  profile login    Launch visible Chrome for manual login, save auth_state.json
  capture-material Capture clean screenshots (no video recording)

Options for 'profile login':
  --url <url>           URL to open (default: https://www.kehuanxiongmao.com)
  --port <port>         CDP port (default: 9333)
  --width <px>          Window width (default: 1280)
  --height <px>         Window height (default: 900)

Options for 'capture-material':
  --profile <id>        Chrome profile id (default: kehuanxiongmao)
  --port <port>         CDP port (default: 9342)
  --mode <mode>         'headless' or 'visible' (default: headless)
  --width <px>          Viewport width (default: 1920)
  --height <px>         Viewport height (default: 1080)
  --output <dir>        Assets output directory (default: ../assets/sites)
  --callouts <file>     Optional callout registry path (default: <output>/_callouts.json)
  --no-homepage         Skip homepage capture
  --no-entry            Skip feature entry capture
  --no-params           Skip feature params capture
  --children <ids>      Comma-separated child ids to capture (e.g. rollup_banner,elevator_ad)

Examples:
  cdp-capture profile login myprofile --url https://example.com
  cdp-capture capture-material poster
  cdp-capture capture-material '*' --mode visible
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

async function cmdCaptureMaterial(args) {
  const moduleId = args._[0];
  if (!moduleId) {
    console.error('Error: module id is required');
    console.error('Usage: cdp-capture capture-material <module-id|*> [options]');
    console.error('  Use * to capture all modules');
    process.exit(1);
  }

  // Parse --children option (comma-separated list of child ids)
  let children = undefined;
  if (args.options.children && typeof args.options.children === 'string') {
    children = args.options.children.split(',').map((s) => s.trim()).filter(Boolean);
  }

  const result = await captureMaterials({
    rootDir: ROOT,
    modules: moduleId,
    profileId: args.options.profile || 'kehuanxiongmao',
    port: parseInt(args.options.port || '9342', 10),
    mode: args.options.mode || 'headless',
    width: parseInt(args.options.width || '1920', 10),
    height: parseInt(args.options.height || '1080', 10),
    outputDir: args.options.output ? path.resolve(args.options.output) : undefined,
    calloutRegistry: args.options.callouts ? path.resolve(args.options.callouts) : undefined,
    captureHomepage: args.options['no-homepage'] !== true,
    captureEntry: args.options['no-entry'] !== true,
    captureParams: args.options['no-params'] !== true,
    children,
  });

  // Print summary to stdout
  console.log(JSON.stringify({
    total_assets: result.assets.length,
    site: result.site,
    callout_registry: result.callout_registry,
    assets: result.assets.map(a => ({
      asset_id: a.asset_id,
      filename: a.filename,
      asset_kind: a.asset_kind,
      module: a.module || null,
    })),
  }, null, 2));
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
      case 'capture-material':
        await cmdCaptureMaterial(args);
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
