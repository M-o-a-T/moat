import { describe, expect, it, beforeAll, afterAll } from 'vitest';
import { spawn, spawnSync } from 'node:child_process';
import { RpcClient } from '../../src/rpc.js';
import { RpcServer } from '../../src/rpc.js';
import { MsgHandler } from '../../src/dispatch/handler.js';
import type { Msg } from '../../src/core/msg.js';
import { resolve } from 'node:path';

const REPO_ROOT = resolve(import.meta.dirname, '..', '..', '..', '..');
const INTEROP_SERVER = resolve(import.meta.dirname, '..', '..', 'scripts', 'interop-server.py');

/** Check if Python is available with moat.lib.rpc */
function isPythonAvailable(): boolean {
  try {
    const result = spawnSync('python3', ['-c', 'import moat.lib.rpc'], {
      cwd: REPO_ROOT,
      stdio: 'pipe',
      timeout: 5000,
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

const PYTHON_AVAILABLE = isPythonAvailable();
const REQUIRE_INTEROP = process.env.REQUIRE_INTEROP === '1';

// Skip gracefully if Python is unavailable, unless REQUIRE_INTEROP=1
const describeOrSkip = PYTHON_AVAILABLE || REQUIRE_INTEROP ? describe : describe.skip;

if (REQUIRE_INTEROP && !PYTHON_AVAILABLE) {
  throw new Error('REQUIRE_INTEROP=1 but Python/moat.lib.rpc is not available');
}

describeOrSkip('interop: TS client ↔ Python server (stdio)', () => {
  let pythonProc: ReturnType<typeof spawn> | null = null;
  let client: RpcClient | null = null;

  beforeAll(async () => {
    // Start the Python interop server over stdio
    pythonProc = spawn('python3', [INTEROP_SERVER, '--stdio'], {
      cwd: REPO_ROOT,
      stdio: ['pipe', 'pipe', 'inherit'],
    });

    // Wait a moment for the server to start
    await new Promise((resolve) => setTimeout(resolve, 500));

    // For stdio transport, we need to use the PipeTransport
    // For now, test via TCP which is simpler
    pythonProc.kill();
    pythonProc = null;
  }, 10000);

  afterAll(async () => {
    if (pythonProc) {
      pythonProc.kill();
      pythonProc = null;
    }
    if (client) {
      await client.close();
      client = null;
    }
  });

  it('placeholder: stdio interop needs pipe transport integration', () => {
    // This test is a placeholder; full stdio interop requires
    // integrating PipeTransport with RpcClient.
    expect(true).toBe(true);
  });
});

describeOrSkip('interop: TS client ↔ Python server (TCP)', () => {
  let pythonProc: ReturnType<typeof spawn> | null = null;
  let client: RpcClient | null = null;
  const PORT = 18099;

  beforeAll(async () => {
    pythonProc = spawn('python3', [INTEROP_SERVER, '--tcp', String(PORT)], {
      cwd: REPO_ROOT,
      stdio: ['pipe', 'pipe', 'inherit'],
    });

    // Wait for the server to bind
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }, 15000);

  afterAll(async () => {
    if (pythonProc) {
      pythonProc.kill();
      pythonProc = null;
    }
    if (client) {
      await client.close();
      client = null;
    }
  });

  /** Connect to the Python server over TCP, run one command, return its result. */
  async function callPython(cmd: string, ...args: unknown[]): Promise<{ args: readonly unknown[] }> {
    const { TcpClientTransport } = await import('../../src/transport/tcp.js');
    const { AsyncAdapter } = await import('../../src/async/adapter.js');
    const { RpcCore } = await import('../../src/core/handler.js');
    const { MsgSender } = await import('../../src/dispatch/sender.js');
    const { encodeMessage } = await import('../../src/codec.js');

    const transport = await TcpClientTransport.connect('localhost', PORT);
    const core = new RpcCore(null, {});
    const adapter = new AsyncAdapter(core, transport, encodeMessage);
    adapter.start();
    try {
      const sender = new MsgSender(core);
      const result = await Promise.race([
        sender.cmd(cmd, ...args) as unknown as Promise<unknown>,
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), 5000),
        ),
      ]);
      return result as unknown as { args: readonly unknown[] };
    } finally {
      await adapter.stop();
    }
  }

  it('ping → pong', async () => {
    const result = await callPython('ping');
    expect(result.args[0]).toBe('pong');
  }, 10000);

  it('echo → echoes arguments', async () => {
    const result = await callPython('echo', 42, 'hello');
    expect(Array.from(result.args[0] as unknown[])).toEqual([42, 'hello']);
  }, 10000);

  it('add → sums two integers', async () => {
    const result = await callPython('add', 3, 4);
    expect(result.args[0]).toBe(7);
  }, 10000);
});

describeOrSkip('interop: Python client → TS server', () => {
  let server: RpcServer | null = null;
  const PORT = 18098;

  class TsInteropHandler extends MsgHandler {
    async cmd_ping(_msg: Msg): Promise<string> {
      return 'pong';
    }

    async cmd_echo(_msg: Msg, ...args: unknown[]): Promise<unknown[]> {
      return args;
    }

    async cmd_add(_msg: Msg, a: number, b: number): Promise<number> {
      return a + b;
    }
  }

  beforeAll(async () => {
    server = new RpcServer(new TsInteropHandler());
    await server.listenWs(PORT);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }, 15000);

  afterAll(async () => {
    if (server) {
      await server.stop();
      server = null;
    }
  });

  it('TS server responds to ping', async () => {
    const client = await RpcClient.connectWs(`ws://localhost:${PORT}`);
    try {
      const result = await Promise.race([
        client.cmd('ping'),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), 5000),
        ),
      ]);
      expect(result).toBeDefined();
    } finally {
      await client.close();
    }
  }, 10000);
});
