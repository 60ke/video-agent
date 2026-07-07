'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { ensureDir, generateTaskId, findFfmpeg, sleep, toCookieParam } = require('./utils');
const { launchChrome, closeChrome } = require('./chrome-launcher');
const { restoreAuthState, getProfileDir, getAuthStatePath } = require('./profile-auth');
const { injectOverlay, mergeOverlayConfig } = require('./overlay');
const { Recorder } = require('./recorder');
const { Timeline } = require('./timeline');
const { EventEmitter } = require('./events');
const { executeAction, waitForLoadEvent } = require('./actions');
const { verifyAndSave } = require('./verifier');

// ── Defaults ─────────────────────────────────────────────────────────────────

const DEFAULT_VIEWPORT = { width: 1920, height: 1080 };
const DEFAULT_RECORDING = {
  fps: 30,
  jpegQuality: 78,
  format: 'mp4',
  videoCodec: 'libx264',
  pixelFormat: 'yuv420p',
  crf: '20',
  preset: 'veryfast',
};
const DEFAULT_CHROME = {
  mode: 'headless',
  extraArgs: [],
  port: 9333,
};
const DEFAULT_OVERLAY = {
  enabled: true,
};

// ── Merge task config with defaults ──────────────────────────────────────────

function resolveTaskConfig(rawTask) {
  const task = { ...rawTask };
  if (!task.profileId && typeof task.url === 'string' && task.url.includes('kehuanxiongmao.com')) {
    task.profileId = 'kehuanxiongmao';
  }
  task.viewport = { ...DEFAULT_VIEWPORT, ...(task.viewport || {}) };
  task.recording = { ...DEFAULT_RECORDING, ...(task.recording || {}) };
  task.chrome = { ...DEFAULT_CHROME, ...(task.chrome || {}) };
  task.overlay = mergeOverlayConfig({ ...DEFAULT_OVERLAY, ...(task.overlay || {}) });
  task.actions = Array.isArray(task.actions) ? task.actions : [];
  return task;
}

function shouldStopRecordingAfter(action) {
  return action && (action.stopRecordingAfter === true || action.recordingBoundary === 'stop_after');
}

// ── Main task runner ─────────────────────────────────────────────────────────

/**
 * Run a capture task from a task JSON object.
 *
 * @param {object} rawTask  - task config
 * @param {string} rootDir  - cdp-capture root directory
 * @returns {Promise<object>} task result
 */
async function runTask(rawTask, rootDir) {
  const task = resolveTaskConfig(rawTask);
  const taskId = generateTaskId();
  const outputDir = path.resolve(task.outputDir || path.join(rootDir, 'output'), taskId);
  const logsDir = path.join(outputDir, 'logs');
  const screenshotsDir = path.join(outputDir, 'screenshots');
  const framesDir = path.join(outputDir, 'frames');
  const cfrDir = path.join(outputDir, 'cfr_frames');
  const videoPath = path.join(outputDir, 'video.mp4');
  const narrationTrackPath = path.join(outputDir, 'recording_narration_track.json');

  // Create directories
  await ensureDir(outputDir);
  await ensureDir(logsDir);
  await ensureDir(screenshotsDir);

  // Save task.json
  await fsp.writeFile(
    path.join(outputDir, 'task.json'),
    JSON.stringify({ ...task, taskId, outputDir }, null, 2),
    'utf8'
  );

  // Set up logging
  const cdpLogPath = path.join(logsDir, 'cdp.log');
  const ffmpegLogPath = path.join(logsDir, 'ffmpeg.log');
  const ndjsonPath = path.join(logsDir, 'events.ndjson');
  fs.writeFileSync(cdpLogPath, '', 'utf8');

  const log = (message) => {
    const line = `[${new Date().toISOString()}] ${message}\n`;
    process.stderr.write(line);
    fs.appendFileSync(cdpLogPath, line, 'utf8');
  };

  // Set up event emitter
  const events = new EventEmitter(ndjsonPath);
  await events.init();

  // Set up timeline
  const timeline = new Timeline();

  // Find ffmpeg
  const ffmpegPath = findFfmpeg();

  let chromeHandle = null;
  let recorder = null;
  let authStateRestored = false;
  let recordingMeta = null;
  let recordingStop = null;

  try {
    events.emit('task.started', { taskId, url: task.url, outputDir });

    // ── Launch Chrome ────────────────────────────────────────────────────────
    const profileDir = getProfileDir(rootDir, task.profileId || 'default');
    const authStatePath = getAuthStatePath(rootDir, task.profileId || 'default');
    log(`Launching Chrome (${task.chrome.mode}) — profile: ${profileDir}`);
    chromeHandle = await launchChrome({
      profileDir,
      port: task.chrome.port,
      width: task.viewport.width,
      height: task.viewport.height,
      mode: task.chrome.mode,
      extraArgs: task.chrome.extraArgs,
      onStderr: (text) => fs.appendFileSync(cdpLogPath, `[chrome] ${text}\n`, 'utf8'),
    });

    const client = chromeHandle.client;

    // Enable CDP domains
    await client.send('Page.enable');
    await client.send('Runtime.enable');
    await client.send('Network.enable');

    // Set device metrics
    await client.send('Emulation.setDeviceMetricsOverride', {
      width: task.viewport.width,
      height: task.viewport.height,
      deviceScaleFactor: 1,
      mobile: false,
    });

    // ── Restore auth state ───────────────────────────────────────────────────
    const authResult = await restoreAuthState(client, {
      rootDir,
      profileId: task.profileId || 'default',
      targetUrl: task.url,
      log,
    });
    const requiresAuthState =
      task.requireAuth === true ||
      (typeof task.url === 'string' && task.url.includes('kehuanxiongmao.com'));
    if (requiresAuthState && !authResult.authState) {
      throw new Error(
        `auth_state.json is required for ${task.profileId || 'default'} before capture: ${authStatePath}`
      );
    }

    // ── Navigate to target URL ───────────────────────────────────────────────
    log(`Navigating to ${task.url}`);
    let loadPromise = waitForLoadEvent(client, 30000);
    await client.send('Page.navigate', { url: task.url });
    const loaded = await loadPromise;
    events.emit('page.loaded', { url: task.url, loaded });

    // Restore storage if auth state exists
    if (typeof authResult.storageRestored === 'function') {
      const storageRestored = await authResult.storageRestored();
      if (authResult.authState || storageRestored) {
        authStateRestored = true;
        log('Reloading page after auth state restoration');
        loadPromise = waitForLoadEvent(client, 30000);
        await client.send('Page.reload', { ignoreCache: false });
        await loadPromise;
      }
    }

    await sleep(1500); // let page settle

    // ── Inject overlay ───────────────────────────────────────────────────────
    if (task.overlay.enabled) {
      log('Injecting overlay');
      await injectOverlay(client, task.overlay);
    }

    // ── Set up recorder ──────────────────────────────────────────────────────
    recorder = new Recorder(client, {
      framesDir,
      cfrDir,
      videoPath,
      fps: task.recording.fps,
      width: task.viewport.width,
      height: task.viewport.height,
      jpegQuality: task.recording.jpegQuality,
      ffmpegPath,
      encode: {
        codec: task.recording.videoCodec,
        crf: task.recording.crf,
        preset: task.recording.preset,
        pixelFormat: task.recording.pixelFormat,
      },
      log,
    });

    // ── Start recording ──────────────────────────────────────────────────────
    log('Starting recording');
    await recorder.start();
    timeline.setOrigin(Date.now());
    events.emit('recording.started', { fps: task.recording.fps, resolution: `${task.viewport.width}x${task.viewport.height}` });

    const finishRecording = async (reason, actionIndex = null) => {
      if (!recorder || !recorder.recording) {
        return recordingMeta;
      }
      log(`Stopping recording and encoding video (${reason})`);
      recordingMeta = await recorder.finish();
      recordingStop = {
        reason,
        actionIndex,
        stoppedAt: new Date().toISOString(),
        durationMs: recordingMeta.durationMs,
      };
      events.emit('recording.finished', {
        rawFrameCount: recordingMeta.rawFrameCount,
        cfrFrameCount: recordingMeta.cfrFrameCount,
        durationMs: recordingMeta.durationMs,
        videoPath,
        reason,
        actionIndex,
      });
      log(`Video written: ${videoPath}`);
      return recordingMeta;
    };

    // ── Execute actions ──────────────────────────────────────────────────────
    const ctx = {
      client,
      task,
      viewport: task.viewport,
      overlayConfig: task.overlay.enabled ? task.overlay : null,
      screenshotsDir,
      log,
    };

    for (let i = 0; i < task.actions.length; i++) {
      const action = task.actions[i];
      const entry = timeline.startAction(action, i);
      events.emit('action.started', { actionIndex: i, actionType: action.type, params: entry.params });

      try {
        const result = await executeAction(ctx, action);
        timeline.finishAction(entry, result);
        events.emit('action.finished', {
          actionIndex: i,
          actionType: action.type,
          durationMs: entry.durationMs,
          status: 'success',
        });
        log(`Action ${i} (${action.type}) completed in ${entry.durationMs}ms`);

        // Re-inject overlay after open_url
        if (action.type === 'open_url' && task.overlay.enabled) {
          await sleep(300);
          await injectOverlay(client, task.overlay);
        }
        if (shouldStopRecordingAfter(action)) {
          await finishRecording('action_boundary', i);
        }
      } catch (err) {
        timeline.finishAction(entry, null, err);
        events.emit('action.finished', {
          actionIndex: i,
          actionType: action.type,
          durationMs: entry.durationMs,
          status: 'failed',
          error: err.message,
        });
        log(`Action ${i} (${action.type}) failed: ${err.message}`);

        // Take failure screenshot
        try {
          const screenshotResult = await ctx.client.send('Page.captureScreenshot', { format: 'png' });
          const failPath = path.join(screenshotsDir, `fail_action_${i}.png`);
          await fsp.writeFile(failPath, Buffer.from(screenshotResult.data, 'base64'));
          timeline.attachScreenshot(entry, failPath);
        } catch (_e) {
          // ignore screenshot errors
        }

        // If action is marked as required, abort the task
        if (action.required) {
          throw new Error(`Required action ${i} (${action.type}) failed: ${err.message}`);
        }
      }
    }

    // ── Stop recording & encode ──────────────────────────────────────────────
    if (!recordingMeta) {
      await finishRecording('end_of_task', null);
    }
    if (!recordingMeta) {
      throw new Error('Recording did not produce metadata');
    }

    // ── Write metadata ───────────────────────────────────────────────────────
    const metadata = {
      taskId,
      url: task.url,
      captureMode: 'cdp_page_start_screencast',
      resolution: `${task.viewport.width}x${task.viewport.height}`,
      fps: task.recording.fps,
      rawFrameCount: recordingMeta.rawFrameCount,
      cfrFrameCount: recordingMeta.cfrFrameCount,
      durationMs: recordingMeta.durationMs,
      durationSeconds: Number((recordingMeta.durationMs / 1000).toFixed(2)),
      profileId: task.profileId || 'default',
      authStateRestored,
      recordingStop,
      postRecordingActionsExecuted: Boolean(recordingStop && recordingStop.actionIndex !== null && recordingStop.actionIndex < task.actions.length - 1),
      chromeMode: task.chrome.mode,
      overlayEnabled: task.overlay.enabled,
      videoPath,
      outputDir,
      createdAt: new Date().toISOString(),
    };
    await fsp.writeFile(path.join(outputDir, 'metadata.json'), JSON.stringify(metadata, null, 2), 'utf8');

    // ── Write timeline ───────────────────────────────────────────────────────
    await timeline.save(path.join(outputDir, 'timeline.json'));
    const narrationTrack = timeline.narrationTrack({ maxEndMs: recordingMeta.durationMs });
    await fsp.writeFile(narrationTrackPath, JSON.stringify(narrationTrack, null, 2), 'utf8');

    // ── Verify ───────────────────────────────────────────────────────────────
    log('Verifying video');
    const verifyResult = await verifyAndSave(videoPath, ffmpegPath, outputDir, {
      width: task.viewport.width,
      height: task.viewport.height,
      fps: task.recording.fps,
    });
    log(`Verification: ${verifyResult.allChecksPassed ? 'PASS' : 'FAIL'}`);

    // ── Clean up frames (optional) ───────────────────────────────────────────
    if (task.cleanupFrames !== false) {
      // Keep frames by default; set cleanupFrames: true to remove
    }

    events.emit('task.finished', {
      taskId,
      videoPath,
      narrationTrackPath,
      outputDir,
      durationMs: recordingMeta.durationMs,
      metadata,
      timeline: timeline.getSummary(),
      verify: { allChecksPassed: verifyResult.allChecksPassed, checks: verifyResult.checks },
    });

    return {
      taskId,
      outputDir,
      videoPath,
      metadata,
      timeline: timeline.getSummary(),
      verify: verifyResult,
    };
  } catch (err) {
    log(`TASK FAILED: ${err.stack || err.message}`);
    events.emit('task.failed', { taskId, error: err.message, stack: err.stack });

    // Try to save timeline even on failure
    try {
      await timeline.save(path.join(outputDir, 'timeline.json'));
    } catch (_e) {
      // ignore
    }

    throw err;
  } finally {
    events.close();
    if (recorder && recorder.recording) {
      await recorder.stop().catch(() => {});
    }
    await closeChrome(chromeHandle).catch(() => {});
  }
}

module.exports = { runTask, resolveTaskConfig };
