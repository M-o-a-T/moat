/**
 * Example MoaT RPC client.
 *
 * Run with: npx tsx examples/client.ts
 */

import { RpcClient } from '../src/rpc.js';

async function main() {
  const client = await RpcClient.connectWs('ws://localhost:8080');
  console.log('Connected to MoaT RPC server');

  try {
    const pong = await client.cmd('ping');
    console.log('ping →', pong);

    const sum = await client.cmd('add', 3, 4);
    console.log('add(3, 4) →', sum);

    const echoed = await client.cmd('echo', 'hello', 42, true);
    console.log('echo("hello", 42, true) →', echoed);
  } catch (err) {
    console.error('RPC error:', err);
  } finally {
    await client.close();
  }
}

main().catch(console.error);
