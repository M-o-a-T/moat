/**
 * Stdin/stdout pipe transport — for interop tests.
 *
 * Drives RPC over a child process's stdin/stdout.
 */

import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { IncrementalDecoder } from './framing.js';

/** Transport interface that the async adapter expects. */
export interface PipeTransport {
  write(data: Uint8Array): Promise<void>;
  onMessage(cb: (msg: unknown[]) => void): void;
  close(): Promise<void>;
}

/**
 * Pipe transport — wraps a child process's stdin/stdout.
 *
 * The child process reads CBOR messages from stdin and writes
 * CBOR messages to stdout.
 */
export class PipeTransport implements PipeTransport {
  private _stdin: NodeJS.WritableStream;
  private _stdout: NodeJS.ReadableStream;
  private _decoder = new IncrementalDecoder();
  private _emitter = new EventEmitter();
  private _closed = false;
  private _cleanup: () => void;

  constructor(stdin: NodeJS.WritableStream, stdout: NodeJS.ReadableStream, cleanup: () => void) {
    this._stdin = stdin;
    this._stdout = stdout;
    this._cleanup = cleanup;
    this._stdout.on('data', (data: Buffer) => {
      this._decoder.feed(new Uint8Array(data));
      for (const msg of this._decoder.drain()) {
        this._emitter.emit('message', msg);
      }
    });
    this._stdout.on('close', () => {
      this._closed = true;
      this._emitter.emit('close');
    });
  }

  /** Spawn a child process and create a pipe transport. */
  static spawn(cmd: string, args: string[] = []): PipeTransport {
    const proc = spawn(cmd, args, { stdio: ['pipe', 'pipe', 'inherit'] });
    const transport = new PipeTransport(
      proc.stdin,
      proc.stdout,
      () => proc.kill(),
    );
    return transport;
  }

  write(data: Uint8Array): Promise<void> {
    if (this._closed) return Promise.reject(new Error('Transport closed'));
    this._stdin.write(data);
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
      this._stdout.once('close', () => resolve());
      this._stdin.end();
      this._cleanup();
    });
  }
}
