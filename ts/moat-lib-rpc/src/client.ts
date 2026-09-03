/**
 * RpcClient — high-level client that connects to a server over a
 * duplex stream (WebSocket, TCP, or generic readable/writable pair),
 * feeds incoming bytes to the core, sends outgoing bytes, and exposes
 * a `call()` method returning a Promise.
 *
 * Handles timeouts and connection lifecycle.
 *
 * Mirrors the Python `MsgSender` + `Caller` API.
 */

import { RpcCore } from './core/handler.js';
import { MsgSender } from './dispatch/sender.js';
import { AsyncAdapter } from './async/adapter.js';
import type { Transport } from './async/adapter.js';
import { MsgResult } from './core/msg.js';
import { encodeMessage } from './codec.js';
import { WsClientTransport } from './transport/ws.js';
import { TcpClientTransport } from './transport/tcp.js';
import { PipeTransport } from './transport/pipe.js';
import { Path } from './path.js';

/** Default call timeout (ms). 0 = no timeout. */
const DEFAULT_TIMEOUT_MS = 0;

/** Options for the client. */
export interface ClientOptions {
  /** Per-call default timeout in ms (0 = no timeout). */
  timeoutMs?: number;
}

/**
 * RpcClient — connects to a MoaT RPC server and provides a `call()`
 * method for issuing commands.
 *
 * ```ts
 * const client = await RpcClient.connectWs('ws://localhost:8080');
 * const result = await client.call('ping');
 * await client.close();
 * ```
 */
export class RpcClient {
  private _adapter: AsyncAdapter | null = null;
  private _core: RpcCore;
  private _sender: MsgSender;
  private _timeoutMs: number;

  private constructor(core: RpcCore, adapter: AsyncAdapter, timeoutMs: number) {
    this._core = core;
    this._adapter = adapter;
    this._sender = new MsgSender(core);
    this._timeoutMs = timeoutMs;
  }

  /** Connect to a WebSocket server. */
  static async connectWs(url: string, opts?: ClientOptions): Promise<RpcClient> {
    const transport = await WsClientTransport.connect(url);
    return RpcClient._createFromTransport(transport, opts);
  }

  /** Connect to a TCP server. */
  static async connectTcp(host: string, port: number, opts?: ClientOptions): Promise<RpcClient> {
    const transport = await TcpClientTransport.connect(host, port);
    return RpcClient._createFromTransport(transport, opts);
  }

  /** Connect over a child process's stdin/stdout (pipe transport). */
  static async connectPipe(
    cmd: string,
    args: string[] = [],
    opts?: { cwd?: string } & ClientOptions,
  ): Promise<RpcClient> {
    const transport = PipeTransport.spawn(cmd, args, opts?.cwd ? { cwd: opts.cwd } : {});
    return RpcClient._createFromTransport(transport, opts);
  }

  /** Connect over an arbitrary Transport (generic readable/writable pair). */
  static async connectTransport(transport: Transport, opts?: ClientOptions): Promise<RpcClient> {
    return RpcClient._createFromTransport(transport, opts);
  }

  private static _createFromTransport(transport: Transport, opts?: ClientOptions): RpcClient {
    const core = new RpcCore(null, {});
    const adapter = new AsyncAdapter(core, transport, encodeMessage);
    adapter.start();
    return new RpcClient(core, adapter, opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  }

  /**
   * Issue a command and await the result.
   *
   * @param cmd - Command path (string or Path).
   * @param args - Positional arguments.
   * @returns The result value from the server.  Smart-unwraps the
   *   `MsgResult`: a single positional arg is returned directly; if the
   *   server returned keyword args, returns the `MsgResult` so the caller
   *   can access both `.args` and `.kw`.
   */
  async call(cmd: Path | string, ...args: unknown[]): Promise<unknown> {
    const caller = this._sender.cmd(cmd, ...args);
    const promise = caller as unknown as Promise<MsgResult>;

    const result =
      this._timeoutMs > 0
        ? await Promise.race([
            promise,
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error('RPC call timed out')), this._timeoutMs),
            ),
          ])
        : await promise;

    return this._unwrapResult(result);
  }

  /** Issue a command with keyword arguments. */
  async callKw(
    cmd: Path | string,
    kw: Record<string, unknown>,
    ...args: unknown[]
  ): Promise<unknown> {
    const caller = this._sender.cmdKw(cmd, kw, ...args);
    const promise = caller as unknown as Promise<MsgResult>;

    const result =
      this._timeoutMs > 0
        ? await Promise.race([
            promise,
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error('RPC call timed out')), this._timeoutMs),
            ),
          ])
        : await promise;

    return this._unwrapResult(result);
  }

  /**
   * Smart-unwrap a MsgResult: single positional arg → return it directly;
   * only kwargs → return the kw dict; mixed → return the MsgResult.
   */
  private _unwrapResult(result: MsgResult): unknown {
    const argsLen = result.args.length;
    const kwKeys = Object.keys(result.kw).length;
    if (kwKeys > 0) {
      return result; // mixed or kw-only: return the hybrid
    }
    if (argsLen === 1) {
      return result.args[0];
    }
    if (argsLen === 0) {
      return undefined;
    }
    return result.args; // multiple positional args: return the array
  }

  /** Get the underlying MsgSender for more advanced usage. */
  get sender(): MsgSender {
    return this._sender;
  }

  /** Get the underlying RpcCore. */
  get core(): RpcCore {
    return this._core;
  }

  /** Disconnect and clean up. */
  async close(): Promise<void> {
    if (this._adapter) {
      await this._adapter.stop();
      this._adapter = null;
    }
  }
}
