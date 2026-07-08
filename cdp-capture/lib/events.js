'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

/**
 * NDJSON event emitter.
 *
 * Writes progress events to stdout (one JSON per line) and to `logs/events.ndjson`.
 *
 * Events:
 *  - capture.started
 *  - page.loaded
 *  - screenshot.saved
 *  - capture.finished
 *  - capture.failed
 */
class EventEmitter {
  constructor(ndjsonLogPath) {
    this.ndjsonLogPath = ndjsonLogPath;
    this._logStream = null;
  }

  async init() {
    if (this.ndjsonLogPath) {
      await fsp.mkdir(path.dirname(this.ndjsonLogPath), { recursive: true });
      this._logStream = fs.createWriteStream(this.ndjsonLogPath, { flags: 'a' });
    }
  }

  emit(event, data = {}) {
    const line = JSON.stringify({
      event,
      timestamp: new Date().toISOString(),
      ...data,
    });
    // stdout — NDJSON for AI consumption
    process.stdout.write(line + '\n');
    // log file
    if (this._logStream) {
      this._logStream.write(line + '\n');
    }
  }

  close() {
    if (this._logStream) {
      this._logStream.end();
    }
  }
}

module.exports = { EventEmitter };
