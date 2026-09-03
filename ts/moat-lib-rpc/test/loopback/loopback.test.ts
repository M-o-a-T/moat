import { describe, expect, it } from 'vitest';
import { RpcCore } from '../../src/core/handler.js';
import { Msg } from '../../src/core/msg.js';
import { StreamLink } from '../../src/core/link.js';
import { MsgHandler } from '../../src/dispatch/handler.js';
import { encodeMessage, decodeMessage } from '../../src/codec.js';
import { AsyncAdapter } from '../../src/async/adapter.js';
import type { Transport } from '../../src/async/adapter.js';

/**
 * In-memory duplex transport — pipes writes to the other side's onMessage callback.
 */
class InMemoryTransport implements Transport {
  private _other: InMemoryTransport | null = null;
  private _cb: ((msg: unknown[]) => void) | null = null;
  private _closed = false;

  connect(other: InMemoryTransport): void {
    this._other = other;
    other._other = this;
  }

  write(data: Uint8Array): Promise<void> {
    if (this._closed) return Promise.reject(new Error('closed'));
    if (this._other?._cb) {
      // Defer to next microtask to simulate async transport. Deliver the
      // decoded message — transports own inbound decoding.
      const msg = decodeMessage(data);
      Promise.resolve().then(() => {
        if (!this._closed && this._other?._cb) {
          this._other._cb(msg);
        }
      });
    }
    return Promise.resolve();
  }

  onMessage(cb: (msg: unknown[]) => void): void {
    this._cb = cb;
  }

  close(): Promise<void> {
    this._closed = true;
    return Promise.resolve();
  }
}

/** Create a pair of connected in-memory transports. */
function createTransportPair(): [InMemoryTransport, InMemoryTransport] {
  const a = new InMemoryTransport();
  const b = new InMemoryTransport();
  a.connect(b);
  return [a, b];
}

/** Small helper to wait for a microtask cycle. */
function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('loopback: TS↔TS in-memory', () => {
  it('simple ping/pong call', async () => {
    class PingHandler extends MsgHandler {
      async cmd_ping(msg: Msg): Promise<unknown> {
        return 'pong';
      }
    }

    const [clientT, serverT] = createTransportPair();
    const serverHandler = new PingHandler();
    const serverCore = new RpcCore(serverHandler, {
      onNewCommand: (msg: Msg) => {
        return serverHandler.handle(msg, msg.rcmd);
      },
    });
    const serverAdapter = new AsyncAdapter(serverCore, serverT, encodeMessage);
    serverAdapter.start();

    const clientCore = new RpcCore(null, {});
    const clientAdapter = new AsyncAdapter(clientCore, clientT, encodeMessage);
    clientAdapter.start();

    const { msg } = clientCore.call('ping', [], {});

    // Wait for the result (with timeout)
    const result = await Promise.race([
      msg.waitReplied(),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 2000),
      ),
    ]);

    expect(result.args[0]).toBe('pong');

    await clientAdapter.stop();
    await serverAdapter.stop();
  });

  it('call with arguments', async () => {
    class EchoHandler extends MsgHandler {
      async cmd_echo(msg: Msg, ...args: unknown[]): Promise<unknown> {
        return args;
      }
    }

    const [clientT, serverT] = createTransportPair();
    const serverHandler = new EchoHandler();
    const serverCore = new RpcCore(serverHandler, {
      onNewCommand: (msg: Msg) => {
        return serverHandler.handle(msg, msg.rcmd);
      },
    });
    const serverAdapter = new AsyncAdapter(serverCore, serverT, encodeMessage);
    serverAdapter.start();

    const clientCore = new RpcCore(null, {});
    const clientAdapter = new AsyncAdapter(clientCore, clientT, encodeMessage);
    clientAdapter.start();

    const { msg } = clientCore.call('echo', [42, 'hello'], {});

    const result = await Promise.race([
      msg.waitReplied(),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 2000),
      ),
    ]);

    // echo returns the args array as a single value
    const echoed = result.args[0] as unknown[];
    expect(echoed[0]).toBe(42);
    expect(echoed[1]).toBe('hello');

    await clientAdapter.stop();
    await serverAdapter.stop();
  });

  it('error forwarding: unknown command', async () => {
    class EmptyHandler extends MsgHandler {}

    const [clientT, serverT] = createTransportPair();
    const serverHandler = new EmptyHandler();
    const serverCore = new RpcCore(serverHandler, {
      onNewCommand: (msg: Msg) => {
        return serverHandler.handle(msg, msg.rcmd).catch(() => {
          // Error already sent by the handler via mlSendError
        });
      },
    });
    const serverAdapter = new AsyncAdapter(serverCore, serverT, encodeMessage);
    serverAdapter.start();

    const clientCore = new RpcCore(null, {});
    const clientAdapter = new AsyncAdapter(clientCore, clientT, encodeMessage);
    clientAdapter.start();

    const { msg } = clientCore.call('nonexistent', [], {});

    await expect(
      Promise.race([
        msg.waitReplied(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), 2000),
        ),
      ]),
    ).rejects.toThrow();

    await clientAdapter.stop();
    await serverAdapter.stop();
  });
});
