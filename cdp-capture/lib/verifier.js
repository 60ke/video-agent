'use strict';

const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const fs = require('node:fs');

/**
 * Verify an output video file using FFmpeg.
 * Parses resolution, fps, duration, codec, and writes verify.json.
 *
 * @param {string} videoPath   - path to the video file
 * @param {string} ffmpegPath  - path to ffmpeg binary
 * @param {object} expected    - expected values { width, height, fps }
 * @returns {Promise<object>}  verification result
 */
async function verifyVideo(videoPath, ffmpegPath, expected = {}) {
  const result = {
    videoPath,
    exists: false,
    fileSize: 0,
    resolution: null,
    width: null,
    height: null,
    fps: null,
    duration: null,
    codec: null,
    pixelFormat: null,
    bitrate: null,
    expected,
    checks: {},
    verifiedAt: new Date().toISOString(),
    error: null,
  };

  // Check file exists
  if (!fs.existsSync(videoPath)) {
    result.error = `Video file not found: ${videoPath}`;
    return result;
  }
  result.exists = true;
  const stat = await fsp.stat(videoPath);
  result.fileSize = stat.size;

  // Run ffprobe / ffmpeg -i to get stream info
  const stderr = await new Promise((resolve, reject) => {
    const ffmpeg = spawn(ffmpegPath, ['-hide_banner', '-i', videoPath], {
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    let output = '';
    ffmpeg.stderr.on('data', (chunk) => {
      output += chunk.toString();
    });
    ffmpeg.on('error', reject);
    ffmpeg.on('close', () => resolve(output));
  });

  // Parse resolution
  const resMatch = stderr.match(/,\s*(\d{2,5})x(\d{2,5})/);
  if (resMatch) {
    result.width = parseInt(resMatch[1], 10);
    result.height = parseInt(resMatch[2], 10);
    result.resolution = `${result.width}x${result.height}`;
  }

  // Parse fps
  const fpsMatch = stderr.match(/(\d+(?:\.\d+)?)\s+(?:fps|tbr)/);
  if (fpsMatch) {
    result.fps = parseFloat(fpsMatch[1]);
  }

  // Parse duration
  const durMatch = stderr.match(/Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)/);
  if (durMatch) {
    const h = parseInt(durMatch[1], 10);
    const m = parseInt(durMatch[2], 10);
    const s = parseFloat(durMatch[3]);
    result.duration = h * 3600 + m * 60 + s;
  }

  // Parse codec
  const codecMatch = stderr.match(/Video:\s*(\w+)/);
  if (codecMatch) {
    result.codec = codecMatch[1];
  }

  // Parse pixel format
  const pixMatch = stderr.match(/yuv\w+/);
  if (pixMatch) {
    result.pixelFormat = pixMatch[0];
  }

  // Parse bitrate
  const bitrateMatch = stderr.match(/(\d+)\s+kb\/s/);
  if (bitrateMatch) {
    result.bitrate = parseInt(bitrateMatch[1], 10);
  }

  // Run checks
  if (expected.width && expected.height) {
    result.checks.resolution = result.width === expected.width && result.height === expected.height;
  }
  if (expected.fps) {
    result.checks.fps = result.fps !== null && Math.abs(result.fps - expected.fps) < 1;
  }
  result.checks.codec = result.codec === 'h264';
  result.checks.duration = result.duration !== null && result.duration > 0;
  result.checks.fileExists = result.exists;
  result.checks.fileSizeOk = result.fileSize > 1000; // at least 1KB

  const allPassed = Object.values(result.checks).every((v) => v === true);
  result.allChecksPassed = allPassed;

  return result;
}

/**
 * Verify and save verify.json in the output directory.
 */
async function verifyAndSave(videoPath, ffmpegPath, outputDir, expected = {}) {
  const result = await verifyVideo(videoPath, ffmpegPath, expected);
  const verifyPath = path.join(outputDir, 'verify.json');
  await fsp.writeFile(verifyPath, JSON.stringify(result, null, 2), 'utf8');
  return result;
}

module.exports = { verifyVideo, verifyAndSave };
