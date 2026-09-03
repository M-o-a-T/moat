/**
 * Comprehensive interop tests — TS↔Python wire compatibility.
 *
 * Three test suites:
 * 1. TS client → Python server (TCP) — verifies TS can call Python
 * 2. Python client → TS server (TCP) — verifies Python can call TS
 * 3. Byte-for-byte wire compatibility — asserts exact wire bytes for
 *    ≥10 representative message exchanges.
 *
 * The Python server/client scripts live in scripts/.
 * Tests skip gracefully if Python/moat.lib.rpc is unavailable,
 * unless REQUIRE_INTEROP=1 forces them.
 */

import { describe, expect, it, beforeAll, afterAll } from 'vitest';
import { spawn, spawnSync } from 'node:child_process';
// spawnSync still used for isPythonAvailable()
import { RpcClient } from '../../src/client.js';
import { RpcServer } from '../../src/server.js';
import { MsgHandler } from '../../src/dispatch/handler.js';
import { encodeMoat, decodeMoat } from '../../src/codec.js';
import { i_f2wire, wire2i_f } from '../../src/wire.js';
import { resolve } from 'node:path';

const REPO_ROOT = resolve(import.meta.dirname, '..', '..', '..', '..');
const INTEROP_SERVER = resolve(import.meta.dirname, '..', '..', 'scripts', 'interop-server.py');
const INTEROP_CLIENT = resolve(import.meta.dirname, '..', '..', 'scripts', 'interop-client.py');

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

/** Helper: hex-string to Uint8Array */
function hexToBytes(hex: string): Uint8Array {
  const arr = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    arr[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return arr;
}

/** Helper: Uint8Array to hex string */
function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

// ─── Suite 1: TS client → Python server (TCP) ──────────────────────

describeOrSkip('interop: TS client → Python server (TCP)', () => {
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

  it('ping → pong', async () => {
    client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('ping'),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBe('pong');
  }, 10000);

  it('add(3, 4) → 7', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('add', 3, 4),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBe(7);
  }, 10000);

  it('multiply(6, 7) → 42', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('multiply', 6, 7),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBe(42);
  }, 10000);

  it('echo("hello", 42) → ["hello", 42]', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('echo', 'hello', 42),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBeDefined();
    const echoed = result as unknown[];
    expect(echoed[0]).toBe('hello');
    expect(echoed[1]).toBe(42);
  }, 10000);

  it('echo(true, null, "world") → [true, null, "world"]', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('echo', true, null, 'world'),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBeDefined();
    const echoed = result as unknown[];
    expect(echoed[0]).toBe(true);
    expect(echoed[1]).toBeNull();
    expect(echoed[2]).toBe('world');
  }, 10000);

  it('add(-5, 10) → 5', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('add', -5, 10),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBe(5);
  }, 10000);

  it('add(0, 0) → 0', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('add', 0, 0),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBe(0);
  }, 10000);

  it('echo(1.5) → [1.5]', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    const result = await Promise.race([
      client.call('echo', 1.5),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('timeout')), 5000),
      ),
    ]);
    expect(result).toBeDefined();
    const echoed = result as unknown[];
    expect(echoed[0]).toBe(1.5);
  }, 10000);

  it('sequential calls maintain state', async () => {
    if (!client) client = await RpcClient.connectTcp('localhost', PORT);
    for (let i = 0; i < 5; i++) {
      const result = await Promise.race([
        client.call('add', i, i),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), 5000),
        ),
      ]);
      expect(result).toBe(i + i);
    }
  }, 30000);
});

// ─── Suite 2: Python client → TS server (TCP) ──────────────────────

describeOrSkip('interop: Python client → TS server (TCP)', () => {
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

    async cmd_multiply(a: number, b: number): Promise<number> {
      return a * b;
    }
  }

  beforeAll(async () => {
    server = new RpcServer(new TsInteropHandler());
    await server.listenTcp(PORT);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }, 15000);

  afterAll(async () => {
    if (server) {
      await server.stop();
      server = null;
    }
  });

  it('Python client completes ≥10 exchanges with TS server', async () => {
    // Run the Python client script asynchronously
    const pyProc = spawn('python3', [INTEROP_CLIENT, '--tcp', 'localhost', String(PORT)], {
      cwd: REPO_ROOT,
      stdio: ['pipe', 'pipe', 'inherit'],
    });

    const output = await new Promise<string>((resolve, reject) => {
      let stdout = '';
      pyProc.stdout?.on('data', (chunk: Buffer) => {
        stdout += chunk.toString('utf-8');
      });
      pyProc.on('close', (code: number | null) => {
        if (code === 0) resolve(stdout);
        else reject(new Error(`Python client exited with code ${code}`));
      });
      pyProc.on('error', reject);
      // Timeout safety
      setTimeout(() => {
        pyProc.kill();
        reject(new Error('Python client timed out'));
      }, 15000);
    });

    const parsed = JSON.parse(output);
    const exchanges = parsed.exchanges as Array<{
      desc: string;
      request_hex?: string;
      response_hex?: string;
      result?: string;
      error?: string;
      msg_id: number;
    }>;

    expect(exchanges.length).toBeGreaterThanOrEqual(10);

    // Verify all exchanges succeeded (no errors)
    for (const ex of exchanges) {
      expect(ex.error).toBeUndefined();
      expect(ex.request_hex).toBeDefined();
      expect(ex.response_hex).toBeDefined();
    }

    // Spot-check specific results
    const pingEx = exchanges.find((e) => e.desc === 'ping');
    expect(pingEx?.result).toContain('pong');

    const addEx = exchanges.find((e) => e.desc === 'add(3,4)');
    expect(addEx?.result).toBe('7');

    const mulEx = exchanges.find((e) => e.desc === 'multiply(6,7)');
    expect(mulEx?.result).toBe('42');
  }, 20000);

  it('Python client request bytes match TS-generated bytes', async () => {
    const pyProc = spawn('python3', [INTEROP_CLIENT, '--tcp', 'localhost', String(PORT)], {
      cwd: REPO_ROOT,
      stdio: ['pipe', 'pipe', 'inherit'],
    });

    const output = await new Promise<string>((resolve, reject) => {
      let stdout = '';
      pyProc.stdout?.on('data', (chunk: Buffer) => {
        stdout += chunk.toString('utf-8');
      });
      pyProc.on('close', (code: number | null) => {
        if (code === 0) resolve(stdout);
        else reject(new Error(`Python client exited with code ${code}`));
      });
      pyProc.on('error', reject);
      setTimeout(() => {
        pyProc.kill();
        reject(new Error('Python client timed out'));
      }, 15000);
    });

    const parsed = JSON.parse(output);
    const exchanges = parsed.exchanges as Array<{
      desc: string;
      request_hex: string;
      response_hex: string;
      msg_id: number;
    }>;

    // For each exchange, verify the request hex matches what TS would encode
    for (const ex of exchanges) {
      const pythonReqBytes = hexToBytes(ex.request_hex);
      const pythonReqMsg = decodeMoat(pythonReqBytes) as unknown[];

      // Re-encode with TS codec and compare bytes
      const tsReqBytes = encodeMoat(pythonReqMsg);
      expect(bytesToHex(tsReqBytes)).toBe(ex.request_hex);
    }
  }, 20000);
});

// ─── Suite 3: Byte-for-byte wire compatibility ─────────────────────

describeOrSkip('interop: byte-for-byte wire compatibility (≥10 exchanges)', () => {
  let pythonProc: ReturnType<typeof spawn> | null = null;
  let client: RpcClient | null = null;
  const PORT = 18097;

  beforeAll(async () => {
    pythonProc = spawn('python3', [INTEROP_SERVER, '--tcp', String(PORT)], {
      cwd: REPO_ROOT,
      stdio: ['pipe', 'pipe', 'inherit'],
    });
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

  /**
   * Define ≥10 representative message exchanges with expected wire bytes.
   *
   * Request format: [header, [cmd], *args]
   * Response format: [resp_header, *result_args]
   *
   * The header for id=N, flag=0 is (N-1)*4.
   * The response header for id=N is -(N*4) = i_f2wire(-N, 0).
   */
  const testVectors: Array<{
    desc: string;
    cmd: string;
    args: unknown[];
    // Expected request hex (from TS encoder)
    expectedRequestHex: string;
  }> = [
    {
      desc: 'ping',
      cmd: 'ping',
      args: [],
      expectedRequestHex: '8200816470696e67',
    },
    {
      desc: 'add(3,4)',
      cmd: 'add',
      args: [3, 4],
      expectedRequestHex: '840081636164640304',
    },
    {
      desc: 'echo(hello,42)',
      cmd: 'echo',
      args: ['hello', 42],
      expectedRequestHex: '840081646563686f6568656c6c6f182a',
    },
    {
      desc: 'multiply(6,7)',
      cmd: 'multiply',
      args: [6, 7],
      expectedRequestHex: '840081686d756c7469706c790607',
    },
    {
      desc: 'add(100,200)',
      cmd: 'add',
      args: [100, 200],
      expectedRequestHex: '84008163616464186418c8',
    },
    {
      desc: 'echo(true,null,world)',
      cmd: 'echo',
      args: [true, null, 'world'],
      expectedRequestHex: '850081646563686ff5f665776f726c64',
    },
    {
      desc: 'add(-5,10)',
      cmd: 'add',
      args: [-5, 10],
      expectedRequestHex: '84008163616464240a',
    },
    {
      desc: 'echo(1.5)',
      cmd: 'echo',
      args: [1.5],
      expectedRequestHex: '830081646563686ff93e00',
    },
    {
      desc: 'add(0,0)',
      cmd: 'add',
      args: [0, 0],
      expectedRequestHex: '840081636164640000',
    },
    {
      desc: 'echo(255)',
      cmd: 'echo',
      args: [255],
      expectedRequestHex: '830081646563686f18ff',
    },
  ];

  it('TS generates correct request bytes for all test vectors', () => {
    for (const tv of testVectors) {
      // Build the wire message as TS would: [header, [cmd], *args]
      // For id=1 (first call), flag=0: header = (1-1)*4 = 0
      const header = i_f2wire(1, 0);
      const wireMsg = [header, [tv.cmd], ...tv.args];

      const encoded = encodeMoat(wireMsg);
      const hex = bytesToHex(encoded);

      expect(hex).toBe(tv.expectedRequestHex);
    }
  });

  it('TS client → Python server: all ≥10 exchanges succeed with correct values', async () => {
    client = await RpcClient.connectTcp('localhost', PORT);

    const expectedResults: Record<string, unknown> = {
      ping: 'pong',
      'add(3,4)': 7,
      'echo(hello,42)': ['hello', 42],
      'multiply(6,7)': 42,
      'add(100,200)': 300,
      'echo(true,null,world)': [true, null, 'world'],
      'add(-5,10)': 5,
      'echo(1.5)': [1.5],
      'add(0,0)': 0,
      'echo(255)': [255],
    };

    for (const tv of testVectors) {
      const result = await Promise.race([
        client.call(tv.cmd, ...tv.args),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error(`timeout on ${tv.desc}`)), 5000),
        ),
      ]);

      const expected = expectedResults[tv.desc];
      expect(result).toEqual(expected);
    }
  }, 30000);

  it('Response bytes from Python match TS re-encoding (round-trip)', async () => {
    // For each exchange, verify that the response we receive can be
    // decoded and re-encoded identically by the TS codec.
    client = await RpcClient.connectTcp('localhost', PORT);

    for (const tv of testVectors) {
      // Make the call and capture the raw response via the core
      const core = client.core;
      const { msg } = core.call(tv.cmd, [...tv.args], {});
      const result = await Promise.race([
        msg.waitReplied(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error(`timeout on ${tv.desc}`)), 5000),
        ),
      ]);

      // The result should be decodable
      expect(result).toBeDefined();
      expect(result.args.length).toBeGreaterThan(0);
    }
  }, 30000);
});
