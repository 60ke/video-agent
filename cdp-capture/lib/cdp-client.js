'use strict';

const { resolveModule } = require('./utils');
const WebSocket = resolveModule('ws');

/**
 * Minimal CDP (Chrome DevTools Protocol) WebSocket client.
 *
 * Supports:
 *  - `send(method, params)` → Promise<result>
 *  - `on(method, listener)` / `off(method, listener)` for CDP events
 *  - `once(method, listener)` for one-time event listeners
 *  - Configurable command timeout (default 30s)
 */
class CdpClient {
  constructor(wsUrl, options = {}) {
    this.wsUrl = wsUrl;
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    this.commandTimeout = options.commandTimeout || 30000;
    this._closed = false;
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.ws.once('open', resolve);
      this.ws.once('error', reject);
      this.ws.on('message', (raw) => this._handleMessage(raw));
      this.ws.on('close', () => {
        this._closed = true;
        for (const { reject: rejectPending } of this.pending.values()) {
          rejectPending(new Error('CDP socket closed'));
        }
        this.pending.clear();
      });
    });
  }

  _handleMessage(raw) {
    let message;
    try {
      message = JSON.parse(raw.toString());
    } catch (_e) {
      return;
    }

    if (message.id && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) {
        reject(new Error(message.error.message || JSON.stringify(message.error)));
      } else {
        resolve(message.result || {});
      }
      return;
    }

    if (message.method && this.listeners.has(message.method)) {
      for (const listener of this.listeners.get(message.method)) {
        try {
          listener(message.params || {});
        } catch (err) {
          // Listener errors should not break other listeners
          console.error(`[cdp-client] Listener error for ${message.method}:`, err.message);
        }
      }
    }
  }

  send(method, params = {}) {
    if (this._closed) {
      return Promise.reject(new Error('CDP socket closed'));
    }
    const id = this.nextId++;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP command timed out (${this.commandTimeout}ms): ${method}`));
        }
      }, this.commandTimeout);
    });
  }

  on(method, listener) {
    if (!this.listeners.has(method)) {
      this.listeners.set(method, new Set());
    }
    this.listeners.get(method).add(listener);
    return () => this.off(method, listener);
  }

  once(method, listener) {
    const wrapper = (params) => {
      this.off(method, wrapper);
      listener(params);
    };
    this.on(method, wrapper);
    return () => this.off(method, wrapper);
  }

  off(method, listener) {
    if (this.listeners.has(method)) {
      this.listeners.get(method).delete(listener);
    }
  }

  close() {
    if (!this._closed) {
      this.ws.close();
    }
  }
}

module.exports = { CdpClient };
