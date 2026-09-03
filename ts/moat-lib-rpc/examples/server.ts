/**
 * Example MoaT RPC server with a few command handlers.
 *
 * Run with: npx tsx examples/server.ts
 */

import { MsgHandler } from '../src/dispatch/handler.js';
import { RpcServer } from '../src/rpc.js';
import type { Msg } from '../src/core/msg.js';

class ExampleHandler extends MsgHandler {
  async cmd_ping(_msg: Msg): Promise<string> {
    return 'pong';
  }

  async cmd_echo(_msg: Msg, ...args: unknown[]): Promise<unknown[]> {
    return args;
  }

  async cmd_add(_msg: Msg, a: number, b: number): Promise<number> {
    return a + b;
  }

  doc_ping = 'Respond with "pong"';
  doc_echo = 'Echo back the arguments';
  doc_add = 'Add two numbers: add(a, b) → a+b';
}

async function main() {
  const handler = new ExampleHandler();
  const server = new RpcServer(handler);
  await server.listenWs(8080);
  console.log('MoaT RPC server listening on ws://localhost:8080');
}

main().catch(console.error);
