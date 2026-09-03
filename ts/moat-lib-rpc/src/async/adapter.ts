/**
 * Async adapter — bridges the sans-IO core with Promises/timers.
 *
 * The core never awaits and has no clock. This adapter:
 *   - Turns core callbacks into Promises/AsyncIterators
 *   - Pumps outbound frames from core.drain() to the transport
 *   - Feeds inbound frames from the transport to core.feed()
 *   - Owns the reuse-delay timer (single unref'ed timer)
 *
 * The reuse delay (~1s) mirrors Python's L-build behaviour:
 * freed ids enter a holding queue and are returned to the tiered pools
 * only after the delay, avoiding late-message races.
 */

import { RpcCore } from '../core/handler.js';
import { StreamLink } from '../core/link.js';
import type { CoreCallbacks } from '../core/link.js';
import { Msg, MsgResult } from '../core/msg.js';
import { decodeStreamError } from '../errors.js';

/** Transport interface — push bytes out, pull decoded messages in.
 *
 * Transports own inbound decoding: ``onMessage`` delivers already-decoded
 * wire messages, so the adapter feeds them straight to the core without
 * a second decode step. (Raw byte transports decode their frames/streams
 * internally before invoking the callback.)
 */
export interface Transport {
  /** Send a message (already CBOR-encoded). */
  write(data: Uint8Array): Promise<void>;
  /** Register a callback for received, decoded messages. */
  onMessage(cb: (msg: unknown[]) => void): void;
  /** Close the transport. */
  close(): Promise<void>;
}

/** Configuration for the async adapter. */
export interface AdapterOptions {
  /** Reuse delay in milliseconds (default 1000, matching Python L-build). */
  reuseDelayMs?: number;
}

const DEFAULT_REUSE_DELAY = 1000;

/** Entry in the pending-free queue. */
interface PendingFree {
  id: number;
  freedAt: number;
}

/**
 * AsyncAdapter — connects the sans-IO RpcCore to a Transport.
 *
 * Usage:
 * ```ts
 * const adapter = new AsyncAdapter(core, transport, encode);
 * await adapter.start();
 * // ... use sender.cmd(...)
 * await adapter.stop();
 * ```
 */
export class AsyncAdapter {
  private _core: RpcCore;
  private _transport: Transport;
  private _encode: (msg: unknown[]) => Uint8Array;
  private _reuseDelayMs: number;
  private _pendingFree: PendingFree[] = [];
  private _delayTimer: ReturnType<typeof setTimeout> | null = null;
  private _running = false;
  private _pumpScheduled = false;

  constructor(
    core: RpcCore,
    transport: Transport,
    encode: (msg: unknown[]) => Uint8Array,
    options: AdapterOptions = {},
  ) {
    this._core = core;
    this._transport = transport;
    this._encode = encode;
    this._reuseDelayMs = options.reuseDelayMs ?? DEFAULT_REUSE_DELAY;
  }

  /** Start the adapter — wires callbacks, begins pumping. */
  start(): void {
    if (this._running) return;
    this._running = true;

    const callbacks = this._core['_callbacks' as keyof RpcCore] as unknown as CoreCallbacks;

    // Wire onDetach to the reuse-delay timer so freed ids are recycled.
    callbacks.onDetach = (id: number) => {
      this._enqueueFree(id);
    };

    // Wrap onNewCommand to pump after the handler produces outbound messages.
    if (callbacks.onNewCommand) {
      const origOnNew = callbacks.onNewCommand;
      callbacks.onNewCommand = (msg: Msg, link: StreamLink) => {
        Promise.resolve(origOnNew(msg, link)).finally(() => this._schedulePump());
      };
    }

    // Wrap core.send to trigger a pump whenever the core queues outbound
    // messages (covers client-side call() and server-side result()).
    const origSend = this._core.send.bind(this._core) as (link: StreamLink, a: unknown[], kw: import('../core/msg.js').OptKw, flag: number) => void;
    this._core.send = (link: StreamLink, a: unknown[], kw: import('../core/msg.js').OptKw, flag: number) => {
      origSend(link, a, kw, flag);
      this._schedulePump();
    };

    this._transport.onMessage((msg: unknown[]) => {
      this._core.feed(msg);
      this._schedulePump();
    });
  }

  /** Stop the adapter. */
  async stop(): Promise<void> {
    this._running = false;
    this._core.closeInput();
    if (this._delayTimer) {
      clearTimeout(this._delayTimer);
      this._delayTimer = null;
    }
    await this._transport.close();
  }

  /** Immediately drain and send outbound messages. */
  pump(): void {
    this._doPump();
  }

  /** Schedule a pump on the next microtask (batching multiple sends). */
  private _schedulePump(): void {
    if (this._pumpScheduled) return;
    this._pumpScheduled = true;
    Promise.resolve().then(() => {
      this._pumpScheduled = false;
      this._doPump();
    });
  }

  /** Drain queued outbound messages and write them to the transport. */
  private _doPump(): void {
    const outbound = this._core.drain();
    for (const msg of outbound) {
      const encoded = this._encode(msg.payload);
      this._transport.write(encoded).catch(() => {
        // Transport write failed — the transport is probably closing
      });
    }
  }

  /** Enqueue a freed id for delayed recycling. */
  private _enqueueFree(id: number): void {
    this._pendingFree.push({ id, freedAt: Date.now() });
    this._scheduleDelay();
  }

  /** Schedule the reuse-delay timer for freed ids. */
  private _scheduleDelay(): void {
    if (this._delayTimer !== null) return;
    if (this._pendingFree.length === 0) return;

    this._delayTimer = setTimeout(() => {
      this._delayTimer = null;
      const now = Date.now();
      const remaining: PendingFree[] = [];

      while (this._pendingFree.length > 0) {
        const entry = this._pendingFree.shift()!;
        if (now - entry.freedAt >= this._reuseDelayMs) {
          this._core.freeId(entry.id);
        } else {
          remaining.push(entry);
        }
      }

      // Put back any that haven't aged enough
      this._pendingFree = remaining;

      // Re-schedule if there are still pending entries
      if (this._pendingFree.length > 0) {
        this._scheduleDelay();
      }
    }, this._reuseDelayMs);

    // unref so the timer doesn't keep the event loop alive
    if (typeof this._delayTimer === 'object' && 'unref' in this._delayTimer) {
      (this._delayTimer as { unref: () => void }).unref();
    }
  }
}
