/**
 * TCP transport for MoaT RPC.
 *
 * Raw TCP sockets with incremental CBOR decode (no length prefix;
 * CBOR is self-delimiting).
 */

import { Socket, createConnection, createServer } from 'node:net';
import { EventEmitter } from 'node:events';
import { IncrementalDecoder } from './framing.js';

/** Transport interface that the async adapter expects. */
export interface TcpTransport {
  write(data: Uint8Array): Promise<void>;
  onMessage(cb: (msg: unknown[]) => void): void;
  close(): Promise<void>;
}

/**
 * TCP client transport — wraps a net.Socket.
 *
 * Uses an IncrementalDecoder to extract individual CBOR messages
 * from the byte stream.
 */
export class TcpClientTransport implements TcpTransport {
  private _socket: Socket;
  private _decoder = new IncrementalDecoder();
  private _emitter = new EventEmitter();
  private _closed = false;

  constructor(socket: Socket) {
    this._socket = socket;
    this._socket.on('data', (data: Buffer) => {
      this._decoder.feed(new Uint8Array(data));
      for (const msg of this._decoder.drain()) {
        this._emitter.emit('message', msg);
      }
    });
    this._socket.on('close', () => {
      this._closed = true;
      this._emitter.emit('close');
    });
    this._socket.on('error', (err: Error) => {
      this._emitter.emit('error', err);
    });
  }

  /** Connect to a TCP server. */
  static connect(host: string, port: number): Promise<TcpClientTransport> {
    return new Promise((resolve, reject) => {
      const socket = createConnection({ host, port }, () => {
        resolve(new TcpClientTransport(socket));
      });
      socket.on('error', reject);
    });
  }

  write(data: Uint8Array): Promise<void> {
    if (this._closed) return Promise.reject(new Error('Transport closed'));
    this._socket.write(data);
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
      this._socket.once('close', () => resolve());
      this._socket.destroy();
    });
  }
}

/**
 * TCP server transport — wraps a single accepted connection.
 */
export class TcpServerTransport implements TcpTransport {
  private _socket: Socket;
  private _decoder = new IncrementalDecoder();
  private _emitter = new EventEmitter();
  private _closed = false;

  constructor(socket: Socket) {
    this._socket = socket;
    this._socket.on('data', (data: Buffer) => {
      this._decoder.feed(new Uint8Array(data));
      for (const msg of this._decoder.drain()) {
        this._emitter.emit('message', msg);
      }
    });
    this._socket.on('close', () => {
      this._closed = true;
      this._emitter.emit('close');
    });
    this._socket.on('error', (err: Error) => {
      this._emitter.emit('error', err);
    });
  }

  write(data: Uint8Array): Promise<void> {
    if (this._closed) return Promise.reject(new Error('Transport closed'));
    this._socket.write(data);
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
      this._socket.once('close', () => resolve());
      this._socket.destroy();
    });
  }
}

/**
 * Convenience: create a TCP server that accepts connections.
 */
export function createTcpServer(port: number, host = 'localhost'): Promise<{
  waitForConnection: () => Promise<TcpServerTransport>;
  close: () => Promise<void>;
}> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(port, host, () => {
      resolve({
        waitForConnection: () =>
          new Promise<TcpServerTransport>((resolveConn) => {
            server.once('connection', (socket: Socket) => {
              resolveConn(new TcpServerTransport(socket));
            });
          }),
        close: () =>
          new Promise<void>((resolveClose) => {
            server.close(() => resolveClose());
          }),
      });
    });
    server.on('error', reject);
  });
}
