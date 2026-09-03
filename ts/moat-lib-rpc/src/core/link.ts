/**
 * StreamLink — pairs the two halves of a sub-channel.
 *
 * Mirrors StreamLink from moat/lib/rpc/stream/base.py.
 *
 * Forwards ml_send/ml_recv, tracks endHere/endThere/endBoth, and
 * detaches from the core when both ends close.
 */

import { EOFError } from '../errors.js';
import {
  B_ERROR,
  B_STREAM,
  B_WARNING_INTERNAL,
} from '../const.js';
import type { RpcCore } from './handler.js';
import { MsgLink } from './msg.js';
import type { Msg, OptKw } from './msg.js';

/** Callbacks the core invokes on the adapter. */
export interface CoreCallbacks {
  /** A new command arrived (server side). */
  onNewCommand?: (msg: Msg, link: StreamLink) => void;
  /** A result/error arrived for an outstanding call (client side). */
  onResult?: (linkId: number, result: { ok: true; args: unknown[]; kw: Record<string, unknown> } | { ok: false; error: Error }) => void;
  /** A warning was received. */
  onWarning?: (linkId: number, warning: Error) => void;
  /** A link was detached (both ends closed). */
  onDetach?: (id: number) => void;
}

/**
 * StreamLink — the handler for messages that forwards them across the stream.
 */
export class StreamLink extends MsgLink {
  private _stream: RpcCore | null;
  /** The sub-channel id (positive if originator, negative if responder). */
  readonly id: number;

  constructor(stream: RpcCore, id: number) {
    super();
    this._stream = stream;
    this.id = id;
  }

  /** Data to be forwarded across the link (to the wire). */
  override async mlRecv(a: unknown[], kw: OptKw, flags: number): Promise<void> {
    if (this._stream === null) throw new EOFError();
    await this._stream.send(this, a, kw, flags);
  }

  /** Data to be forwarded to our remote (from the wire). */
  override async mlSend(a: unknown[], kw: OptKw, flags: number): Promise<void> {
    await super.mlSend(a, kw, flags);
  }

  /** Called when this stream is done — detach from the core. */
  override streamDetach(): void {
    if (this._stream !== null) {
      this._stream.detach(this);
      this._stream = null;
    }
  }
}
