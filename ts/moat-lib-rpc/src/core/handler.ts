/**
 * RpcCore — sans-IO RPC multiplexer.
 *
 * Mirrors HandlerStream from moat/lib/rpc/stream/base.py.
 *
 * The core is a pure, synchronous state machine with no promises,
 * timers, or I/O. Async behaviour lives in the transport/async layers.
 *
 * Inputs (sync):  core.feed(message: unknown[])
 * Outputs (sync): core.drain()
 *
 * The core uses pull-based output (drain) which composes best with
 * deterministic sans-IO tests. The async adapter pumps these to the transport.
 */

import { EOFError } from '../errors.js';
import {
  B_ERROR,
  B_STREAM,
  B_WARNING,
  B_WARNING_INTERNAL,
  E_CANCEL,
  E_ERROR,
  E_NO_CMD,
  E_NO_CMDS,
  E_NO_STREAM,
  E_SKIP,
} from '../const.js';
import { wire2i_f, i_f2wire } from '../wire.js';
import { decodeStreamError, Flow, StreamError } from '../errors.js';
import { Path } from '../path.js';
import { pushKw, popKw } from '../proxy.js';
import { Msg, MsgResult, type OptKw } from './msg.js';
import { StreamLink, type CoreCallbacks } from './link.js';

/** Outbound message ready for the wire. */
export interface OutboundMsg {
  readonly wire: number; // packed header
  readonly payload: unknown[]; // [header, *args, ?kwMap]
}

/** Command handler function type. */
export type CommandHandler = (msg: Msg, rcmd: (string | number | boolean | null)[]) => Promise<void>;

/** Interface for a command dispatcher (MsgHandler equivalent). */
export interface CommandDispatcher {
  handle(msg: Msg, rcmd: (string | number | boolean | null)[]): Promise<void>;
}

/**
 * RpcCore — the sans-IO multiplexer.
 *
 * Holds the live sub-channel map (id → StreamLink), the id allocator,
 * and (phase 2) per-direction credit counters.
 */
export class RpcCore {
  private _msgs = new Map<number, StreamLink>();
  private _sendQueue: { link: StreamLink; a: unknown[]; kw: OptKw; flag: number }[] = [];
  private _callbacks: CoreCallbacks = {};

  // ID allocation — tiered free-id pools
  private _idCounter = 0;
  private _id1 = new Set<number>(); // ids < 6
  private _id2 = new Set<number>(); // ids < 64
  private _id3 = new Set<number>(); // rest

  // Freed ids awaiting reuse-delay (owned by the async adapter, but
  // the core tracks them for isIdle checking)
  private _pendingFree: Set<number> = new Set();

  private _closing = false;
  private _handler: CommandDispatcher | null;

  constructor(handler: CommandDispatcher | null = null, callbacks: CoreCallbacks = {}) {
    this._handler = handler;
    this._callbacks = callbacks;
  }

  get isIdle(): boolean {
    if (this._msgs.size > 0) return false;
    if (this._sendQueue.length > 0) return false;
    if (this._pendingFree.size > 0) return false;
    return true;
  }

  get closing(): boolean {
    return this._closing;
  }

  /** Set the command handler. */
  setHandler(handler: CommandDispatcher | null): void {
    this._handler = handler;
  }

  /** Close: no more messages accepted. */
  closeInput(): void {
    this._closing = true;
  }

  // --- ID allocation ---

  /** Allocate the next free positive id. */
  private _genId(): number {
    if (this._id1.size > 0) {
      const id = this._id1.values().next().value!;
      this._id1.delete(id);
      return id;
    }
    if (this._id2.size > 0) {
      const id = this._id2.values().next().value!;
      this._id2.delete(id);
      return id;
    }
    if (this._id3.size > 0) {
      const id = this._id3.values().next().value!;
      this._id3.delete(id);
      return id;
    }
    this._idCounter += 1;
    return this._idCounter;
  }

  /**
   * Free an id (called by the adapter after the reuse delay).
   * Tiered: <6 → _id1, <64 → _id2, rest → _id3.
   */
  freeId(id: number): void {
    if (id <= 0) return; // remote ids are not recycled
    this._pendingFree.delete(id);
    if (id < 6) {
      this._id1.add(id);
    } else if (id < 64) {
      this._id2.add(id);
    } else {
      this._id3.add(id);
    }
  }

  /** Mark an id as pending-free (waiting for reuse delay). */
  markPendingFree(id: number): void {
    if (id > 0) this._pendingFree.add(id);
  }

  // --- Link management ---

  /** Attach a link. */
  attach(link: StreamLink): void {
    if (this._msgs.has(link.id)) {
      throw new Error(`MID ${link.id} already known`);
    }
    this._msgs.set(link.id, link);
  }

  /** Detach a link. */
  detach(link: StreamLink): void {
    const mid = link.id;
    if (this._msgs.get(mid) !== link) return; // already removed
    this._msgs.delete(mid);
    if (mid <= 0) return; // remote ids: don't recycle

    // Notify the adapter about the freed id
    this._callbacks.onDetach?.(mid);
  }

  // --- Sending (queued, pulled by drain) ---

  /** Queue a message for sending (called by StreamLink.mlRecv). */
  send(link: StreamLink, a: unknown[], kw: OptKw, flag: number): void {
    if (this._closing) throw new EOFError();
    this._sendQueue.push({ link, a, kw, flag });
  }

  /** Drain: get all queued outbound messages (pull-based). */
  drain(): OutboundMsg[] {
    const msgs: OutboundMsg[] = [];
    while (this._sendQueue.length > 0) {
      const { link, a, kw, flag } = this._sendQueue.shift()!;
      const wire = i_f2wire(link.id, flag);
      const payload: unknown[] = [wire, ...a];
      pushKw(payload, kw, flag === B_WARNING);
      msgs.push({ wire, payload });
    }
    return msgs;
  }

  // --- Receiving ---

  /**
   * Feed an incoming wire message.
   *
   * @param msg - The decoded CBOR array: [header, *args, ?kwMap]
   * @returns The StreamLink if a new one was created, or null if routed to existing.
   */
  feed(msg: unknown[]): StreamLink | null {
    if (msg.length === 0) {
      throw new Error('Empty message');
    }

    const header = msg[0] as number;
    const [rawId, flag] = wire2i_f(header);

    // Incoming: flip the sign
    const i = -rawId;

    const a = msg.slice(1) as unknown[];
    const internal = flag === B_WARNING && a.length === 1 && typeof a[0] === 'number';
    const kw = internal ? null : (() => {
      // pop_kw mutates the array
      const k = popKw(a);
      return Object.keys(k).length > 0 ? k : null;
    })();

    const stream = flag & B_STREAM;
    const error = flag & B_ERROR;
    let effectiveFlag = flag;
    if (internal && stream && error) {
      effectiveFlag = B_WARNING_INTERNAL;
    }

    const link = this._msgs.get(i);

    if (link === undefined) {
      // Spurious or new message
      if (i > 0) {
        // Spurious message for unknown positive id — log and drop
        return null;
      }
      if (error) {
        // Spurious error — log and drop
        return null;
      }

      // New incoming call: assemble the message
      const cmd = a.length > 0 ? a.shift() : Path.EMPTY;
      const cmdPath = cmd instanceof Path ? cmd : Array.isArray(cmd) ? Path.build(cmd) : Path.build([cmd as string]);

      const realKw = kw ?? {};
      const rem = Msg.Call(cmdPath, a, realKw, effectiveFlag);

      // Build a stream link for it
      const newLink = new StreamLink(this, i);
      rem.replaceWith(newLink);
      if (!stream) {
        newLink.setEnd();
      }
      this.attach(newLink);

      // Spawn the handler (via callback — the adapter handles async)
      if (this._callbacks.onNewCommand) {
        this._callbacks.onNewCommand(rem, newLink);
      }

      return newLink;
    }

    // Route to existing link
    try {
      // Deliver to the link's remote (the Msg)
      const remote = link.remote as Msg | null;
      if (remote) {
        // ml_recv is async in Python, but the core is sync.
        // We call it synchronously — the Msg stores the result.
        // The async adapter wraps this.
        remote.mlRecv(a, kw, effectiveFlag).catch(() => {
          // Errors are handled by the Msg state machine
        });
      }

      // Check if both ends are done
      if (link.endBoth) {
        this.detach(link);
      }
    } catch {
      // If delivery fails, send E_NO_STREAM
      this.send(link, [E_NO_STREAM], null, B_ERROR);
      this.detach(link);
    }

    return null;
  }

  // --- Client-side: initiate a call ---

  /**
   * Initiate a new outgoing call.
   *
   * @param cmd - The command path.
   * @param args - Positional arguments.
   * @param kw - Keyword arguments.
   * @param canStream - Whether streaming is requested (phase 2).
   * @returns [link, msg] — the StreamLink and the Msg to await.
   */
  call(
    cmd: Path | string,
    args: unknown[],
    kw: Record<string, unknown>,
    canStream = false,
  ): { link: StreamLink; msg: Msg } {
    if (this._closing) throw new EOFError();

    const cmdPath = typeof cmd === 'string' ? Path.build([cmd]) : cmd;
    const rcmd = cmdPath.reverse();

    const i = this._genId();
    const msg = Msg.Call(cmdPath, [...args], { ...kw });
    const link = new StreamLink(this, i);
    msg.replaceWith(link);
    this.attach(link);

    // Queue the initial message: [rcmd, *args, ?kw]
    const wireArgs: unknown[] = [rcmd, ...msg.args];
    const flag = canStream ? B_STREAM : 0;
    this.send(link, wireArgs, msg._kw, flag);

    if (!canStream) {
      // Mark the outgoing direction as ended
      msg.setEnd();
    }

    return { link, msg };
  }
}
