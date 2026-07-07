'use strict';

const fsp = require('node:fs/promises');

/**
 * Timeline tracker — records each action's start/end time, params, result, and errors.
 */
class Timeline {
  constructor() {
    this.entries = [];
    this.originMs = Date.now();
  }

  setOrigin(originMs) {
    this.originMs = originMs || Date.now();
  }

  /**
   * Start tracking an action.
   * @returns {object} action record (pass to finishAction)
   */
  startAction(action, index) {
    const entry = {
      index,
      type: action.type,
      params: { ...action },
      startedAt: new Date().toISOString(),
      startedAtMs: Date.now(),
      relativeStartedMs: null,
      finishedAt: null,
      durationMs: null,
      relativeFinishedMs: null,
      status: 'running',
      result: null,
      error: null,
      screenshot: null,
    };
    // Remove type from params (it's in the top-level)
    delete entry.params.type;
    this.entries.push(entry);
    return entry;
  }

  /**
   * Finish an action record.
   */
  finishAction(entry, result = null, error = null) {
    entry.finishedAt = new Date().toISOString();
    entry.durationMs = Date.now() - entry.startedAtMs;
    entry.relativeStartedMs = Math.max(0, entry.startedAtMs - this.originMs);
    entry.relativeFinishedMs = entry.relativeStartedMs + entry.durationMs;
    entry.status = error ? 'failed' : 'success';
    entry.result = result;
    entry.error = error ? (error.message || String(error)) : null;
    return entry;
  }

  /**
   * Attach a screenshot path to the last entry.
   */
  attachScreenshot(entry, screenshotPath) {
    entry.screenshot = screenshotPath;
  }

  /**
   * Save timeline to JSON file.
   */
  async save(filePath) {
    const data = {
      generatedAt: new Date().toISOString(),
      originMs: this.originMs,
      totalActions: this.entries.length,
      actions: this.entries,
    };
    await fsp.writeFile(filePath, JSON.stringify(data, null, 2), 'utf8');
  }

  narrationTrack(options = {}) {
    const maxEndMs = typeof options.maxEndMs === 'number' ? options.maxEndMs : null;
    const segments = [];
    for (const entry of this.entries) {
      const narration = entry.params && typeof entry.params.narration === 'string'
        ? entry.params.narration.trim()
        : '';
      if (!narration || entry.status !== 'success') continue;
      const startMs = typeof entry.relativeStartedMs === 'number'
        ? entry.relativeStartedMs
        : Math.max(0, entry.startedAtMs - this.originMs);
      const endMs = typeof entry.relativeFinishedMs === 'number'
        ? entry.relativeFinishedMs
        : startMs + (entry.durationMs || 800);
      if (maxEndMs !== null && startMs > maxEndMs) continue;
      const safeEndMs = Math.max(endMs, startMs + 300);
      segments.push({
        action_index: entry.index,
        action_type: entry.type,
        start: Number((startMs / 1000).toFixed(3)),
        end: Number(((maxEndMs === null ? safeEndMs : Math.min(safeEndMs, maxEndMs)) / 1000).toFixed(3)),
        text: narration,
      });
    }
    return {
      schema_version: 1,
      source: 'cdp-capture timeline action.narration',
      generatedAt: new Date().toISOString(),
      segments,
    };
  }

  cameraTrack(options = {}) {
    const maxEndMs = typeof options.maxEndMs === 'number' ? options.maxEndMs : null;
    const durationMs = maxEndMs || Math.max(
      0,
      ...this.entries.map((entry) => (
        typeof entry.relativeFinishedMs === 'number'
          ? entry.relativeFinishedMs
          : Math.max(0, (entry.startedAtMs || this.originMs) - this.originMs) + (entry.durationMs || 0)
      ))
    );
    const focusEntries = this.entries
      .filter((entry) => entry.status === 'success' && entry.params && typeof entry.params.cameraFocus === 'string')
      .map((entry) => {
        const startMs = typeof entry.relativeStartedMs === 'number'
          ? entry.relativeStartedMs
          : Math.max(0, entry.startedAtMs - this.originMs);
        const endMs = typeof entry.relativeFinishedMs === 'number'
          ? entry.relativeFinishedMs
          : startMs + (entry.durationMs || 800);
        return {
          action_index: entry.index,
          action_type: entry.type,
          focus: entry.params.cameraFocus,
          startMs,
          endMs,
          selector: entry.params.selector || null,
        };
      })
      .filter((entry) => maxEndMs === null || entry.startMs <= maxEndMs)
      .sort((a, b) => a.startMs - b.startMs);

    const segments = [];
    const introEnd = Math.min(durationMs, focusEntries.length ? Math.max(500, focusEntries[0].startMs - 250) : durationMs);
    segments.push({
      start: 0,
      end: Number((introEnd / 1000).toFixed(3)),
      focus: 'full_page',
      transition: 'hold',
    });
    for (let i = 0; i < focusEntries.length; i++) {
      const entry = focusEntries[i];
      const next = focusEntries[i + 1];
      const startMs = Math.max(0, entry.startMs - 350);
      const naturalEnd = next ? Math.max(entry.endMs + 250, next.startMs - 180) : durationMs;
      const endMs = Math.min(durationMs, Math.max(startMs + 400, naturalEnd));
      segments.push({
        action_index: entry.action_index,
        action_type: entry.action_type,
        selector: entry.selector,
        start: Number((startMs / 1000).toFixed(3)),
        end: Number((endMs / 1000).toFixed(3)),
        focus: entry.focus,
        transition: 'smooth',
      });
    }
    return {
      schema_version: 1,
      source: 'cdp-capture timeline action.cameraFocus',
      generatedAt: new Date().toISOString(),
      duration: Number((durationMs / 1000).toFixed(3)),
      segments: segments.filter((segment) => segment.end > segment.start),
    };
  }

  postRecordingResultProof(recordingStop) {
    if (!recordingStop || typeof recordingStop.actionIndex !== 'number') {
      return { hasResultCapture: false, resultActions: [] };
    }
    const resultActions = [];
    for (const entry of this.entries) {
      if (entry.index <= recordingStop.actionIndex || entry.status !== 'success') continue;
      const params = entry.params || {};
      const result = entry.result || {};
      const workflowStep = String(params.workflowStep || result.workflow_step || '').toLowerCase();
      const pathValue = String(result.path || '');
      const isResult =
        params.resultAsset === true ||
        ['result_crop', 'result_export', 'result_gallery'].includes(workflowStep) ||
        pathValue.replace(/\\/g, '/').includes('/results/');
      if (!isResult) continue;
      resultActions.push({
        action_index: entry.index,
        action_type: entry.type,
        workflow_step: workflowStep || 'result_capture',
        path: result.path || null,
        selector: params.selector || null,
      });
    }
    return {
      hasResultCapture: resultActions.length > 0,
      resultActions,
    };
  }

  /**
   * Get a summary of the timeline.
   */
  getSummary() {
    return {
      total: this.entries.length,
      succeeded: this.entries.filter((e) => e.status === 'success').length,
      failed: this.entries.filter((e) => e.status === 'failed').length,
      narrated: this.entries.filter((e) => e.params && e.params.narration).length,
      cameraFocused: this.entries.filter((e) => e.params && e.params.cameraFocus).length,
    };
  }
}

module.exports = { Timeline };
