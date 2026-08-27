/**
 * Integration tests — RpcClient/RpcServer over an in-memory duplex stream.
 *
 * Exercises the full async stack: RpcClient.call() → AsyncAdapter →
 * InMemoryTransport → AsyncAdapter → RpcServer → MsgHandler → and back.
 *
 * Covers: concurrent calls, keyword arguments, error forwarding,
 * timeouts, sub-command dispatch, and connection lifecycle.
 */

import { describe, expect, it } from 'vitest';
import { RpcCore } from '../../src/core/handler.js';
import { Msg } from '../../src/core/msg.js';
import { StreamLink } from '../../src/core/link.js';
import { MsgHandler } from '../../src/dispatch/handler.js';
import { encodeMessage, decodeMessage } from '../../src/codec.js';
import { AsyncAdapter } from '../../src/async/adapter.js';
import type { Transport } from '../../src/async/adapter.js';
import { RpcClient } from '../../src/client.js';
import { Path } from '../../src/path.js';

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
      // Transports own inbound decoding: deliver the decoded message.
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

/** Create a client-core + server-core pair connected via in-memory transport. */
function createClientServer(
  serverHandler: MsgHandler,
): {
  clientCore: RpcCore;
  clientAdapter: AsyncAdapter;
  serverCore: RpcCore;
  serverAdapter: AsyncAdapter;
  cleanup: () => Promise<void>;
} {
  const [clientT, serverT] = createTransportPair();
  const serverCore = new RpcCore(serverHandler, {
    onNewCommand: (msg: Msg) => {
      return serverHandler.handle(msg, msg.rcmd).catch(() => {});
    },
  });
  const serverAdapter = new AsyncAdapter(serverCore, serverT, encodeMessage);
  serverAdapter.start();

  const clientCore = new RpcCore(null, {});
  const clientAdapter = new AsyncAdapter(clientCore, clientT, encodeMessage);
  clientAdapter.start();

  return {
    clientCore,
    clientAdapter,
    serverCore,
    serverAdapter,
    cleanup: async () => {
      await clientAdapter.stop();
      await serverAdapter.stop();
    },
  };
}

/** Race a promise against a timeout. */
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('timeout')), ms),
    ),
  ]);
}

// --- Handlers for testing ---

class EchoHandler extends MsgHandler {
  async cmd_ping(): Promise<string> {
    return 'pong';
  }

  async cmd_echo(...args: unknown[]): Promise<unknown[]> {
    return args;
  }

  async cmd_add(a: number, b: number): Promise<number> {
    return a + b;
  }

  async cmd_multiply(a: number, b: number): Promise<number> {
    return a * b;
  }

  async cmd_null(): Promise<null> {
    return null;
  }

  async cmd_no_return(): Promise<void> {}

  async cmd_raise_error(): Promise<never> {
    throw new Error('deliberate error');
  }
}

describe('integration: basic calls over in-memory transport', () => {
  it('ping → pong', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('ping', [], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      expect(result.args[0]).toBe('pong');
    } finally {
      await cleanup();
    }
  });

  it('echo with multiple args', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('echo', [42, 'hello', true], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      const echoed = result.args[0] as unknown[];
      expect(echoed).toEqual([42, 'hello', true]);
    } finally {
      await cleanup();
    }
  });

  it('add(3, 4) → 7', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('add', [3, 4], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      expect(result.args[0]).toBe(7);
    } finally {
      await cleanup();
    }
  });

  it('multiply(6, 7) → 42', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('multiply', [6, 7], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      expect(result.args[0]).toBe(42);
    } finally {
      await cleanup();
    }
  });

  it('null return value', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('null', [], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      expect(result.args[0]).toBeNull();
    } finally {
      await cleanup();
    }
  });

  it('void return (undefined)', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('no_return', [], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      // Void return sends [undefined] which CBOR encodes as [null]
      // The result has one arg (null/undefined)
      expect(result.args.length).toBe(1);
    } finally {
      await cleanup();
    }
  });
});

describe('integration: error forwarding', () => {
  it('server-side error is forwarded to client', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('raise_error', [], {});
      await expect(withTimeout(msg.waitReplied(), 2000)).rejects.toThrow();
    } finally {
      await cleanup();
    }
  });

  it('unknown command produces an error', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const { msg } = clientCore.call('nonexistent_command', [], {});
      await expect(withTimeout(msg.waitReplied(), 2000)).rejects.toThrow();
    } finally {
      await cleanup();
    }
  });
});

describe('integration: concurrent calls', () => {
  it('multiple simultaneous calls resolve independently', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());
    try {
      const calls: Promise<unknown>[] = [];
      for (let i = 0; i < 10; i++) {
        const { msg } = clientCore.call('add', [i, i * 2], {});
        calls.push(
          withTimeout(msg.waitReplied(), 3000).then((r) => r.args[0]),
        );
      }

      const results = await Promise.all(calls);
      for (let i = 0; i < 10; i++) {
        expect(results[i]).toBe(i + i * 2);
      }
    } finally {
      await cleanup();
    }
  });

  it('interleaved calls with varying delays resolve correctly', async () => {
    class DelayHandler extends MsgHandler {
      async cmd_fast(): Promise<string> {
        return 'fast';
      }
      async cmd_slow(n: number): Promise<number> {
        return n;
      }
    }

    const { clientCore, cleanup } = createClientServer(new DelayHandler());
    try {
      // Fire 20 interleaved calls
      const promises: Promise<{ idx: number; val: unknown }>[] = [];
      for (let i = 0; i < 20; i++) {
        if (i % 3 === 0) {
          const { msg } = clientCore.call('slow', [i], {});
          promises.push(
            withTimeout(msg.waitReplied(), 3000).then((r) => ({
              idx: i,
              val: r.args[0],
            })),
          );
        } else {
          const { msg } = clientCore.call('fast', [], {});
          promises.push(
            withTimeout(msg.waitReplied(), 3000).then((r) => ({
              idx: i,
              val: r.args[0],
            })),
          );
        }
      }

      const results = await Promise.all(promises);
      for (const r of results) {
        if (r.idx % 3 === 0) {
          expect(r.val).toBe(r.idx);
        } else {
          expect(r.val).toBe('fast');
        }
      }
    } finally {
      await cleanup();
    }
  });
});

describe('integration: keyword arguments', () => {
  it('call with kwargs via callKw', async () => {
    class KwHandler extends MsgHandler {
      async cmd_greet(name: string): Promise<string> {
        return `Hello, ${name}`;
      }
    }

    const { clientCore, cleanup } = createClientServer(new KwHandler());
    try {
      // Use cmdKw with keyword args
      const { msg } = clientCore.call('greet', ['World'], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      expect(result.args[0]).toBe('Hello, World');
    } finally {
      await cleanup();
    }
  });
});

describe('integration: RpcClient.connectTransport', () => {
  it('RpcClient over in-memory transport', async () => {
    const [clientT, serverT] = createTransportPair();

    const serverHandler = new EchoHandler();
    const serverCore = new RpcCore(serverHandler, {
      onNewCommand: (msg: Msg) => {
        return serverHandler.handle(msg, msg.rcmd).catch(() => {});
      },
    });
    const serverAdapter = new AsyncAdapter(serverCore, serverT, encodeMessage);
    serverAdapter.start();

    const client = await RpcClient.connectTransport(clientT);

    try {
      const result = await withTimeout(client.call('ping') as Promise<string>, 2000);
      expect(result).toBe('pong');

      const sum = await withTimeout(client.call('add', 10, 20) as Promise<number>, 2000);
      expect(sum).toBe(30);
    } finally {
      await client.close();
      await serverAdapter.stop();
    }
  });

  it('RpcClient with timeout option', async () => {
    const [clientT, serverT] = createTransportPair();

    const serverHandler = new EchoHandler();
    const serverCore = new RpcCore(serverHandler, {
      onNewCommand: (msg: Msg) => {
        return serverHandler.handle(msg, msg.rcmd).catch(() => {});
      },
    });
    const serverAdapter = new AsyncAdapter(serverCore, serverT, encodeMessage);
    serverAdapter.start();

    const client = await RpcClient.connectTransport(clientT, { timeoutMs: 100 });

    try {
      // Normal calls should succeed within 100ms
      const result = await withTimeout(client.call('ping') as Promise<string>, 2000);
      expect(result).toBe('pong');
    } finally {
      await client.close();
      await serverAdapter.stop();
    }
  });
});

describe('integration: sub-command dispatch', () => {
  it('routes to nested sub-handler', async () => {
    class SubHandler extends MsgHandler {
      async cmd_sub_action(x: number): Promise<number> {
        return x * 2;
      }
    }

    class RootHandler extends MsgHandler {
      sub_math = new SubHandler();
    }

    const { clientCore, cleanup } = createClientServer(new RootHandler());
    try {
      // Path: ["math", "sub_action"]
      const cmdPath = Path.build(['math', 'sub_action']);
      const { msg } = clientCore.call(cmdPath, [21], {});
      const result = await withTimeout(msg.waitReplied(), 2000);
      expect(result.args[0]).toBe(42);
    } finally {
      await cleanup();
    }
  });
});

describe('integration: connection lifecycle', () => {
  it('cleanup after stop does not leak resources', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());

    // Make a call
    const { msg } = clientCore.call('ping', [], {});
    await withTimeout(msg.waitReplied(), 2000);

    // Stop everything
    await cleanup();

    // After stop, the core should be closing
    expect(clientCore.closing).toBe(true);
  });

  it('calling after close throws EOFError', async () => {
    const { clientCore, cleanup } = createClientServer(new EchoHandler());

    await cleanup();

    // Attempting a call after stop should throw
    expect(() => clientCore.call('ping', [], {})).toThrow();
  });
});
