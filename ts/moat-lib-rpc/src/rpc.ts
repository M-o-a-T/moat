/**
 * High-level RpcServer and RpcClient — convenience wrappers.
 *
 * These combine the sans-IO core, async adapter, codec, and transport
 * into a simple-to-use API.
 */

import { RpcCore } from './core/handler.js';
import { Msg } from './core/msg.js';
import { StreamLink } from './core/link.js';
import { MsgHandler } from './dispatch/handler.js';
import { MsgSender } from './dispatch/sender.js';
import { AsyncAdapter } from './async/adapter.js';
import { encodeMessage } from './codec.js';
import {
  WsClientTransport,
  WsServerTransport,
  createWsServer,
} from './transport/ws.js';
import type { WsTransport } from './transport/ws.js';
import { Path } from './path.js';

/**
 * RpcServer — high-level server that registers command handlers
 * and listens for connections.
 */
export class RpcServer {
  private _handlers: MsgHandler;
  private _adapters: AsyncAdapter[] = [];

  constructor(handlers: MsgHandler) {
    this._handlers = handlers;
  }

  /** Listen on a WebSocket port and serve connections. */
  async listenWs(port: number, host = 'localhost'): Promise<void> {
    const { server, waitForConnection, close } = await createWsServer(port, host);

    // Accept connections in a loop
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

    acceptLoop();

    // Store close function for stop()
    (this as unknown as { _closeServer: () => Promise<void> })._closeServer = close;
  }

  private _handleConnection(transport: WsTransport): void {
    const core = new RpcCore(this._handlers, {
      onNewCommand: (msg: Msg, _link: StreamLink) => {
        // Dispatch the command through the handler
        const rcmd = msg.rcmd;
        this._handlers.handle(msg, rcmd).catch((_err: unknown) => {
          // Error already sent by the handler
        });
      },
      onDetach: (_id: number) => {
        // The adapter handles reuse delay
      },
    });

    const adapter = new AsyncAdapter(core, transport, encodeMessage);

    adapter.start();
    this._adapters.push(adapter);
  }

  /** Stop the server. */
  async stop(): Promise<void> {
    for (const adapter of this._adapters) {
      await adapter.stop();
    }
    this._adapters = [];
    const closer = (this as unknown as { _closeServer?: () => Promise<void> })._closeServer;
    if (closer) await closer();
  }
}

/**
 * RpcClient — high-level client that connects to a server
 * and provides a MsgSender for issuing commands.
 */
export class RpcClient {
  private _adapter: AsyncAdapter | null = null;
  private _core: RpcCore;
  private _sender: MsgSender;

  private constructor(core: RpcCore, adapter: AsyncAdapter) {
    this._core = core;
    this._adapter = adapter;
    this._sender = new MsgSender(core);
  }

  /** Connect to a WebSocket server. */
  static async connectWs(url: string): Promise<RpcClient> {
    const transport = await WsClientTransport.connect(url);

    const core = new RpcCore(null, {
      onDetach: (_id: number) => {
        // The adapter handles reuse delay
      },
    });

    const adapter = new AsyncAdapter(core, transport, encodeMessage);

    adapter.start();

    return new RpcClient(core, adapter);
  }

  /** Issue a command. Returns a thenable Caller. */
  cmd(cmd: Path | string, ...args: unknown[]): Promise<unknown> {
    return Promise.resolve(this._sender.cmd(cmd, ...args));
  }

  /** Get the underlying MsgSender for more advanced usage. */
  get sender(): MsgSender {
    return this._sender;
  }

  /** Disconnect. */
  async close(): Promise<void> {
    if (this._adapter) {
      await this._adapter.stop();
      this._adapter = null;
    }
  }
}
