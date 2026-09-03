/**
 * RpcServer — high-level server that accepts connections, feeds bytes
 * to per-connection core instances, and dispatches incoming requests
 * to user-supplied handler functions.
 *
 * Mirrors the Python `BaseListenCmd` / `BaseListenOneCmd` pattern:
 * accept connections, create a per-connection core + adapter, dispatch
 * incoming commands through the supplied `MsgHandler`.
 */

import { RpcCore } from './core/handler.js';
import { Msg } from './core/msg.js';
import { StreamLink } from './core/link.js';
import { MsgHandler } from './dispatch/handler.js';
import { AsyncAdapter } from './async/adapter.js';
import { encodeMessage } from './codec.js';
import { createWsServer } from './transport/ws.js';
import { createTcpServer } from './transport/tcp.js';
import type { Transport } from './async/adapter.js';

/** Options for the server. */
export interface ServerOptions {
  /** Host to bind (default 'localhost'). */
  host?: string;
}

/**
 * RpcServer — accepts connections and serves RPC commands.
 *
 * Each connection gets its own `RpcCore` + `AsyncAdapter` instance,
 * sharing the same `MsgHandler` for command dispatch.
 */
export class RpcServer {
  private _handler: MsgHandler;
  private _adapters: AsyncAdapter[] = [];
  private _closeServer: (() => Promise<void>) | null = null;

  constructor(handler: MsgHandler) {
    this._handler = handler;
  }

  /** Listen on a WebSocket port and serve connections. */
  async listenWs(port: number, opts?: ServerOptions): Promise<void> {
    const host = opts?.host ?? 'localhost';
    const { waitForConnection, close } = await createWsServer(port, host);
    this._closeServer = close;

    const acceptLoop = async () => {
      while (true) {
        try {
          const transport = await waitForConnection();
          this._handleConnection(transport);
        } catch {
          break; // server closed
        }
      }
    };
    acceptLoop().catch(() => {});
  }

  /** Listen on a TCP port and serve connections. */
  async listenTcp(port: number, opts?: ServerOptions): Promise<void> {
    const host = opts?.host ?? 'localhost';
    const { waitForConnection, close } = await createTcpServer(port, host);
    this._closeServer = close;

    const acceptLoop = async () => {
      while (true) {
        try {
          const transport = await waitForConnection();
          this._handleConnection(transport);
        } catch {
          break;
        }
      }
    };
    acceptLoop().catch(() => {});
  }

  /** Handle a single connection (WebSocket or TCP). */
  private _handleConnection(transport: Transport): void {
    const core = new RpcCore(this._handler, {
      onNewCommand: (msg: Msg, _link: StreamLink) => {
        return this._handler.handle(msg, msg.rcmd).catch(() => {
          // Error already sent by the handler
        });
      },
    });

    const adapter = new AsyncAdapter(core, transport, encodeMessage);
    adapter.start();
    this._adapters.push(adapter);
  }

  /** Stop the server and all active connections. */
  async stop(): Promise<void> {
    for (const adapter of this._adapters) {
      await adapter.stop();
    }
    this._adapters = [];
    if (this._closeServer) {
      await this._closeServer();
      this._closeServer = null;
    }
  }
}
