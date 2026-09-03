/**
 * WebSocket transport for MoaT RPC.
 *
 * Binary WS frames carry CBOR-encoded RPC messages.
 * Text WS frames are not used by RPC — they are reserved for serialized
 * HTML/XML (DOM objects) on the Python side (see follow-up moat-ad2.1).
 * The TS WS transport only emits/consumes binary frames and ignores/
 * tears-down on unexpected text frames.
 */

import { EventEmitter } from 'node:events';
import { WebSocket, WebSocketServer } from 'ws';
import { encodeMessage, decodeMessage } from '../codec.js';
import type { OutboundMsg } from '../core/handler.js';

/** Transport interface that the async adapter expects. */
export interface WsTransport {
  write(data: Uint8Array): Promise<void>;
  onMessage(cb: (msg: unknown[]) => void): void;
  close(): Promise<void>;
}

/**
 * WebSocket client transport.
 *
 * Wraps a ws.WebSocket to conform to the Transport interface.
 */
export class WsClientTransport implements WsTransport {
  private _ws: WebSocket;
  private _emitter = new EventEmitter();
  private _closed = false;

  constructor(ws: WebSocket) {
    this._ws = ws;
    this._ws.on('message', (data: Buffer, isBinary: boolean) => {
      if (!isBinary) {
        // Text frame — unexpected for RPC. Tear down.
        this._ws.terminate();
        return;
      }
      this._emitter.emit('message', decodeMessage(new Uint8Array(data)));
    });
    this._ws.on('close', () => {
      this._closed = true;
      this._emitter.emit('close');
    });
    this._ws.on('error', (err: Error) => {
      this._emitter.emit('error', err);
    });
  }

  /** Connect to a WebSocket server. */
  static connect(url: string): Promise<WsClientTransport> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      ws.on('open', () => resolve(new WsClientTransport(ws)));
      ws.on('error', reject);
    });
  }

  write(data: Uint8Array): Promise<void> {
    if (this._closed) return Promise.reject(new Error('Transport closed'));
    this._ws.send(data);
    return Promise.resolve();
  }

  onMessage(cb: (msg: unknown[]) => void): void {
    this._emitter.on('message', cb);
  }

  onClose(cb: () => void): void {
    this._emitter.on('close', cb);
  }

  onError(cb: (err: Error) => void): void {
    this._emitter.on('error', cb);
  }

  close(): Promise<void> {
    return new Promise((resolve) => {
      if (this._closed) {
        resolve();
        return;
      }
      this._ws.once('close', () => resolve());
      this._ws.close();
    });
  }
}

/**
 * WebSocket server transport — wraps a single accepted connection.
 *
 * For multi-connection servers, accept connections and create a
 * WsClientTransport for each.
 */
export class WsServerTransport implements WsTransport {
  private _ws: WebSocket;
  private _emitter = new EventEmitter();
  private _closed = false;

  constructor(ws: WebSocket) {
    this._ws = ws;
    this._ws.on('message', (data: Buffer, isBinary: boolean) => {
      if (!isBinary) {
        this._ws.terminate();
        return;
      }
      this._emitter.emit('message', decodeMessage(new Uint8Array(data)));
    });
    this._ws.on('close', () => {
      this._closed = true;
      this._emitter.emit('close');
    });
    this._ws.on('error', (err: Error) => {
      this._emitter.emit('error', err);
    });
  }

  write(data: Uint8Array): Promise<void> {
    if (this._closed) return Promise.reject(new Error('Transport closed'));
    this._ws.send(data);
    return Promise.resolve();
  }

  onMessage(cb: (msg: unknown[]) => void): void {
    this._emitter.on('message', cb);
  }

  close(): Promise<void> {
    return new Promise((resolve) => {
      if (this._closed) {
        resolve();
        return;
      }
      this._ws.once('close', () => resolve());
      this._ws.close();
    });
  }
}

/**
 * Convenience: create a WebSocket server that accepts connections
 * and yields WsServerTransport instances.
 */
export function createWsServer(port: number, host = 'localhost'): Promise<{
  server: WebSocketServer;
  waitForConnection: () => Promise<WsServerTransport>;
  close: () => Promise<void>;
}> {
  return new Promise((resolve, reject) => {
    const wss = new WebSocketServer({ port, host }, () => {
      resolve({
        server: wss,
        waitForConnection: () =>
          new Promise<WsServerTransport>((resolveConn, rejectConn) => {
            wss.once('connection', (ws: WebSocket) => {
              resolveConn(new WsServerTransport(ws));
            });
            wss.once('error', rejectConn);
          }),
        close: () =>
          new Promise<void>((resolveClose) => {
            wss.close(() => resolveClose());
          }),
      });
    });
    wss.on('error', reject);
  });
}
