'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { ensureDir, sleep } = require('./utils');

/**
 * Screencast recorder — uses CDP `Page.startScreencast` to capture JPEG frames,
 * then builds a CFR (constant frame rate) sequence and encodes to MP4.
 */
class Recorder {
  /**
   * @param {CdpClient} client
   * @param {object} options
   * @param {string} options.framesDir    - directory for raw frames
   * @param {string} options.cfrDir       - directory for CFR frames
   * @param {string} options.videoPath    - output video path
   * @param {number} options.fps          - target FPS (default 30)
   * @param {number} options.width        - capture width
   * @param {number} options.height       - capture height
   * @param {number} options.jpegQuality  - JPEG quality 1-100 (default 78)
   * @param {string} options.ffmpegPath   - path to ffmpeg binary
   * @param {object} options.encode       - encoding options (codec, crf, preset, pixelFormat)
   * @param {function} options.log        - logger function
   */
  constructor(client, options) {
    this.client = client;
    this.framesDir = options.framesDir;
    this.cfrDir = options.cfrDir;
    this.videoPath = options.videoPath;
    this.fps = options.fps || 30;
    this.width = options.width;
    this.height = options.height;
    this.jpegQuality = options.jpegQuality || 78;
    this.ffmpegPath = options.ffmpegPath;
    this.encode = {
      codec: 'libx264',
      crf: '20',
      preset: 'veryfast',
      pixelFormat: 'yuv420p',
      ...(options.encode || {}),
    };
    this.log = options.log || (() => {});

    this.frames = [];
    this.recording = false;
    this.startTime = 0;
    this.endTime = 0;
    this._frameCount = 0;

    // Bind the frame handler
    this._handleFrame = this._handleFrame.bind(this);
    client.on('Page.screencastFrame', this._handleFrame);
  }

  async _handleFrame(params) {
    // Always ack the frame to keep the screencast flowing
    try {
      await this.client.send('Page.screencastFrameAck', { sessionId: params.sessionId });
    } catch (_e) {
      // ignore ack errors
    }

    if (!this.recording) return;

    try {
      const t = (Date.now() - this.startTime) / 1000;
      const frameNum = String(++this._frameCount).padStart(6, '0');
      const framePath = path.join(this.framesDir, `frame_${frameNum}.jpg`);
      await fsp.writeFile(framePath, Buffer.from(params.data, 'base64'));
      this.frames.push({
        path: framePath,
        t,
        timestamp: params.metadata && params.metadata.timestamp,
      });
    } catch (err) {
      this.log(`Frame write error: ${err.message}`);
    }
  }

  /**
   * Start screencast recording.
   */
  async start() {
    await ensureDir(this.framesDir);
    this.recording = true;
    this.startTime = Date.now();
    this._frameCount = 0;
    this.frames = [];

    await this.client.send('Page.startScreencast', {
      format: 'jpeg',
      quality: this.jpegQuality,
      maxWidth: this.width,
      maxHeight: this.height,
      everyNthFrame: 1,
    });
    this.log('Screencast started');
  }

  /**
   * Stop screencast recording.
   */
  async stop() {
    this.recording = false;
    this.endTime = Date.now();
    await this.client.send('Page.stopScreencast').catch(() => {});
    this.log(`Captured ${this.frames.length} raw screencast frames`);
  }

  /**
   * Build CFR (constant frame rate) frame sequence from raw frames.
   * @returns {number} number of CFR frames
   */
  async buildCfrFrames() {
    if (this.frames.length === 0) {
      throw new Error('No screencast frames captured');
    }

    await ensureDir(this.cfrDir);
    const durationMs = this.endTime - this.startTime;
    const durationSeconds = Math.max(durationMs / 1000, this.frames[this.frames.length - 1].t);
    const outputFrameCount = Math.max(1, Math.ceil(durationSeconds * this.fps));

    let cursor = 0;
    for (let i = 0; i < outputFrameCount; i++) {
      const targetT = i / this.fps;
      while (cursor + 1 < this.frames.length && this.frames[cursor + 1].t <= targetT) {
        cursor += 1;
      }
      const dest = path.join(this.cfrDir, `frame_${String(i + 1).padStart(6, '0')}.jpg`);
      await fsp.copyFile(this.frames[cursor].path, dest);
    }

    this.log(`Built ${outputFrameCount} CFR frames (from ${this.frames.length} raw, duration: ${durationSeconds.toFixed(2)}s)`);
    return outputFrameCount;
  }

  /**
   * Encode CFR frames to MP4 using FFmpeg.
   */
  async encodeVideo(frameCount) {
    const inputPattern = path.join(this.cfrDir, 'frame_%06d.jpg');
    const args = [
      '-y',
      '-framerate', String(this.fps),
      '-i', inputPattern,
      '-frames:v', String(frameCount),
      '-c:v', this.encode.codec,
      '-preset', this.encode.preset,
      '-crf', this.encode.crf,
      '-pix_fmt', this.encode.pixelFormat,
      '-movflags', '+faststart',
      this.videoPath,
    ];

    this.log(`ffmpeg ${args.join(' ')}`);

    return new Promise((resolve, reject) => {
      const ffmpeg = spawn(this.ffmpegPath, args, {
        stdio: ['ignore', 'ignore', 'pipe'],
      });
      let stderr = '';
      ffmpeg.stderr.on('data', (chunk) => {
        stderr += chunk.toString();
      });
      ffmpeg.on('error', (err) => {
        reject(new Error(`FFmpeg spawn error: ${err.message}`));
      });
      ffmpeg.on('close', (code) => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`FFmpeg failed with code ${code}: ${stderr.slice(-1200)}`));
        }
      });
    });
  }

  /**
   * Full pipeline: stop → build CFR → encode.
   * @returns {object} metadata about the recording
   */
  async finish() {
    await this.stop();
    const cfrFrameCount = await this.buildCfrFrames();
    await this.encodeVideo(cfrFrameCount);

    return {
      rawFrameCount: this.frames.length,
      cfrFrameCount,
      durationMs: this.endTime - this.startTime,
      fps: this.fps,
      resolution: `${this.width}x${this.height}`,
      videoPath: this.videoPath,
    };
  }
}

module.exports = { Recorder };
