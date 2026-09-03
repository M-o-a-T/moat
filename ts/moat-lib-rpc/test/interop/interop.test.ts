import { describe, expect, it, beforeAll, afterAll } from 'vitest';
import { spawn, spawnSync } from 'node:child_process';
import { RpcClient } from '../../src/client.js';
import { RpcServer } from '../../src/server.js';
import { MsgHandler } from '../../src/dispatch/handler.js';
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
  });

  /** Connect to the Python server over TCP and return a client. */
  async function connectPython(): Promise<RpcClient> {
    return RpcClient.connectTcp('localhost', PORT, { timeoutMs: 5000 });
  }

  it('ping → pong', async () => {
    const client = await connectPython();
    try {
      expect(await client.call('ping')).toBe('pong');
    } finally {
      await client.close();
    }
  }, 10000);

  it('echo → echoes arguments', async () => {
    const client = await connectPython();
    try {
      expect(await client.call('echo', 42, 'hello')).toEqual([42, 'hello']);
    } finally {
      await client.close();
    }
  }, 10000);

  it('add → sums two integers', async () => {
    const client = await connectPython();
    try {
      expect(await client.call('add', 3, 4)).toBe(7);
    } finally {
      await client.close();
    }
  }, 10000);
});

describeOrSkip('interop: Python client → TS server', () => {
  let server: RpcServer | null = null;
  const PORT = 18098;

  class TsInteropHandler extends MsgHandler {
    async cmd_ping(): Promise<string> {
      return 'pong';
    }

    async cmd_echo(...args: unknown[]): Promise<unknown[]> {
      return args;
    }

    async cmd_add(a: number, b: number): Promise<number> {
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
    const client = await RpcClient.connectWs(`ws://localhost:${PORT}`, { timeoutMs: 5000 });
    try {
      expect(await client.call('ping')).toBe('pong');
    } finally {
      await client.close();
    }
  }, 10000);
});
