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

/** Transport interface — push/pull bytes or frames. */
export interface Transport {
  /** Send a message (already CBOR-encoded). */
  write(data: Uint8Array): Promise<void>;
  /** Register a callback for received messages. */
  onMessage(cb: (data: Uint8Array) => void): void;
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
 * const adapter = new AsyncAdapter(core, transport, codec);
 * await adapter.start();
 * // ... use sender.cmd(...)
 * await adapter.stop();
 * ```
 */
export class AsyncAdapter {
  private _core: RpcCore;
  private _transport: Transport;
  private _encode: (msg: unknown[]) => Uint8Array;
  private _decode: (data: Uint8Array) => unknown;
  private _reuseDelayMs: number;
  private _pendingFree: PendingFree[] = [];
  private _delayTimer: ReturnType<typeof setTimeout> | null = null;
  private _running = false;
  private _pumpScheduled = false;
  private _newCommandHandler: ((msg: Msg, link: StreamLink) => Promise<void>) | null = null;

  constructor(
    core: RpcCore,
    transport: Transport,
    encode: (msg: unknown[]) => Uint8Array,
    decode: (data: Uint8Array) => unknown,
    options: AdapterOptions = {},
  ) {
    this._core = core;
    this._transport = transport;
    this._encode = encode;
    this._decode = decode;
    this._reuseDelayMs = options.reuseDelayMs ?? DEFAULT_REUSE_DELAY;
  }

  /** Set the handler for new incoming commands (server side). */
  setCommandHandler(handler: (msg: Msg, link: StreamLink) => Promise<void>): void {
    this._newCommandHandler = handler;
  }

  /** Start the adapter — registers transport listener, begins pumping. */
  start(): void {
    if (this._running) return;
    this._running = true;

    // Hook onDetach to pump after links close
    const origCallbacks = this._core['_callbacks' as keyof RpcCore] as unknown as CoreCallbacks;
    if (origCallbacks.onNewCommand) {
      const origOnNew = origCallbacks.onNewCommand;
      origCallbacks.onNewCommand = (msg: Msg, link: StreamLink) => {
        // Call the original handler, then pump any resulting outbound messages
        Promise.resolve(origOnNew(msg, link)).finally(() => {
          this._pump();
        });
      };
    }

    // Also pump after the core sends (e.g. client initiating a call)
    // We patch the core's send method to trigger a pump
    const origSend = this._core.send.bind(this._core) as (link: StreamLink, a: unknown[], kw: import('../core/msg.js').OptKw, flag: number) => void;
    this._core.send = (link: StreamLink, a: unknown[], kw: import('../core/msg.js').OptKw, flag: number) => {
      origSend(link, a, kw, flag);
      // Pump on next microtask to batch multiple sends
      if (!this._pumpScheduled) {
        this._pumpScheduled = true;
        Promise.resolve().then(() => {
          this._pumpScheduled = false;
          this._pump();
        });
      }
    };

    this._transport.onMessage((data: Uint8Array) => {
      const decoded = this._decode(data) as unknown[];
      if (Array.isArray(decoded)) {
        this._core.feed(decoded);
        this._pump();
      }
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

  /** Pump outbound messages from the core to the transport. */
  private _pump(): void {
    const outbound = this._core.drain();
    for (const msg of outbound) {
      const encoded = this._encode(msg.payload);
      this._transport.write(encoded).catch(() => {
        // Transport write failed — the transport is probably closing
      });
    }
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
