/**
 * @moat/lib-rpc — TypeScript port of MoaT's moat.lib.rpc.
 *
 * Wire-compatible CBOR RPC with Python interop. Sans-IO core +
 * async client/server, WebSocket and TCP transports.
 *
 * @packageDocumentation
 */

// Constants
export * from './const.js';

// Errors
export * from './errors.js';

// Wire protocol (header packing)
export { i_f2wire, wire2i_f, roundtrip } from './wire.js';

// Codec
export {
  encodeMoat,
  decodeMoat,
  encodeMessage,
  decodeMessage,
  Tag,
  Path,
  DProxy,
  Proxy,
  asProxy,
  name2obj,
  pushKw,
  popKw,
  encodeError,
  unwrapObj,
  decodeProxy,
} from './codec.js';

// Path type
export { Path as PathType } from './path.js';
export type { PathElem } from './path.js';

// Core (sans-IO)
export { RpcCore } from './core/handler.js';
export type { OutboundMsg, CommandHandler } from './core/handler.js';
export { StreamLink } from './core/link.js';
export type { CoreCallbacks } from './core/link.js';
export { Msg, MsgLink, MsgResult } from './core/msg.js';
export type { OptKw } from './core/msg.js';

// Dispatch
export { MsgHandler } from './dispatch/handler.js';
export { MsgSender, Caller } from './dispatch/sender.js';
export type { ListMode } from './dispatch/sender.js';

// Async adapter
export { AsyncAdapter } from './async/adapter.js';
export type { Transport, AdapterOptions } from './async/adapter.js';

// Transports
export { IncrementalDecoder } from './transport/framing.js';
export {
  WsClientTransport,
  WsServerTransport,
  createWsServer,
} from './transport/ws.js';
export type { WsTransport } from './transport/ws.js';
export {
  TcpClientTransport,
  TcpServerTransport,
  createTcpServer,
} from './transport/tcp.js';
export type { TcpTransport } from './transport/tcp.js';
export { PipeTransport } from './transport/pipe.js';

// High-level convenience
export { RpcServer, RpcClient } from './rpc.js';
