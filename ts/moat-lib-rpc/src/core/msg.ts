/**
 * Msg envelope — a single RPC call/result.
 *
 * Mirrors moat/lib/rpc/msg.py (non-streaming parts for Phase 1).
 *
 * Phase 1 supports only the single-result (non-streaming) lifecycle:
 * S_NEW → S_END. Streaming arrives in Phase 2.
 */

import { EOFError } from '../errors.js';
import {
  B_ERROR,
  B_STREAM,
  B_WARNING,
  B_WARNING_INTERNAL,
  S_END,
  S_NEW,
  S_ON,
  S_OFF,
  SD_NONE,
  SD_IN,
  SD_OUT,
  SD_BOTH,
  E_CANCEL,
  E_ERROR,
  E_NO_STREAM,
  E_SKIP,
} from '../const.js';
import { decodeStreamError, Flow, NotGiven, StreamError } from '../errors.js';
import { Path } from '../path.js';
import type { PathElem } from '../path.js';
import { popKw, pushKw } from '../proxy.js';

/** Type alias for optional kwargs. */
export type OptKw = Record<string, unknown> | null;

/**
 * MsgResult — simultaneously a list and a dict (read-only).
 * Returned to callers.
 */
export class MsgResult {
  constructor(
    private _a: unknown[],
    private _kw: Record<string, unknown>,
  ) {}

  get args(): readonly unknown[] {
    return this._a;
  }

  get kw(): Record<string, unknown> {
    return this._kw;
  }

  get length(): number {
    return this._a.length;
  }

  get(i: number): unknown {
    return this._a[i];
  }

  getKey(k: string): unknown {
    return this._kw[k];
  }

  /**
   * Convert to a list for wire encoding.
   * @param dictOnly - true: return dict if only kw; false: always list+kw; null: disambiguate.
   */
  toList(dictOnly: boolean | null = true): unknown[] | Record<string, unknown> {
    if (dictOnly === true && Object.keys(this._kw).length > 0 && this._a.length === 0) {
      return this._kw;
    }
    const a = [...this._a];
    if (dictOnly === false) {
      a.push(this._kw);
    } else {
      pushKw(a, this._kw);
    }
    return a;
  }

  [Symbol.iterator](): Iterator<unknown> {
    return this._a[Symbol.iterator]();
  }
}

/** Callback type for ml_recv. */
export type MlRecvFn = (a: unknown[], kw: OptKw, flags: number) => Promise<void>;

/**
 * MsgLink — bidirectional tunnel between two message halves.
 * ml_send on one side delivers to ml_recv of the other.
 */
export class MsgLink {
  protected _remote: MsgLink | null = null;
  protected _end = false;
  readonly linkId: number;

  private static _nextId = 0;

  constructor() {
    this.linkId = ++MsgLink._nextId;
  }

  /** Called from the other side with data. Override this. */
  async mlRecv(_a: unknown[], _kw: OptKw, _flags: number): Promise<void> {
    throw new Error('NotImplementedError');
  }

  /** Forward data to the other side. Don't override. */
  async mlSend(a: unknown[], kw: OptKw, flags: number): Promise<void> {
    if (this._remote === null) throw new EOFError();
    try {
      await this._remote.mlRecv(a, kw, flags);
    } catch (e) {
      await this.kill();
      throw e;
    }
    if (!(flags & B_STREAM)) {
      this.setEnd();
    }
  }

  /** Send an error to the other side. */
  async mlSendError(exc: Error): Promise<void> {
    if (this.endHere) {
      // Log but don't send after end
      return;
    }
    try {
      await this.mlSend([exc], null, B_ERROR);
    } catch {
      try {
        await this.mlSend([exc.constructor.name], null, B_ERROR);
      } catch {
        try {
          await this.mlSend([E_ERROR], null, B_ERROR);
        } catch {
          // give up
        }
      }
    }
  }

  get endBoth(): boolean {
    if (this._remote && !this._remote.endHere) return false;
    return this._end;
  }

  get endHere(): boolean {
    return this._end;
  }

  get endThere(): boolean {
    if (this._remote === null) return true;
    return this._remote.endHere;
  }

  get remote(): MsgLink | null {
    return this._remote;
  }

  /** Called when this stream is done. Override for cleanup. Idempotent. */
  streamDetach(): void {}

  /** Mark the send side as ended. */
  setEnd(): void {
    this._end = true;
    if (this.endBoth) {
      if (this._remote !== null) {
        this._remote.streamDetach();
      }
      this.streamDetach();
      this._remote = null;
    }
  }

  /** Kill: no further communication possible. */
  async kill(): Promise<void> {
    const rem = this._remote;
    if (!this._end) {
      const rs = rem === null ? this : rem;
      rs.setEnd();
      try {
        await rs.mlRecv([E_CANCEL], null, B_ERROR);
      } catch {
        // ignore
      }
    }
  }

  /** Set or change the remote side. Kills the old remote. */
  setRemote(remote: MsgLink): void {
    const rem = this._remote;
    if (rem !== null) {
      rem._remote = null;
      rem.setEnd();
    }
    this._remote = remote;
  }

  toString(): string {
    return `<${this.constructor.name}:L${this.linkId} r=${this._remote ? `L${this._remote.linkId}` : '-'}>`;
  }
}

/**
 * Msg — message encapsulation and data streaming.
 *
 * Phase 1: non-streaming only (S_NEW → S_END).
 */
export class Msg extends MsgLink {
  _cmd: Path | null = null;
  _a: unknown[] = [];
  _kw: Record<string, unknown> = {};

  // Stream states (phase 2; phase 1 uses S_NEW → S_END)
  _streamIn: number = S_NEW;
  _streamOut: number = S_NEW;
  _dir: number = SD_NONE;

  // Result storage
  private _result: { ok: true; value: [unknown[], Record<string, unknown>] } | { ok: false; error: Error } | null = null;
  private _resultResolve: ((value: MsgResult | Promise<MsgResult>) => void) | null = null;
  private _resultPromise: Promise<MsgResult> | null = null;

  warnings: Error[] = [];

  constructor() {
    super();
  }

  get cmd(): Path | null {
    return this._cmd;
  }

  /** Reversed command path (for dispatch). */
  get rcmd(): PathElem[] {
    if (this._cmd === null) return [];
    return this._cmd.reverse();
  }

  get args(): readonly unknown[] {
    return this._a;
  }

  get kw(): Record<string, unknown> {
    return this._kw;
  }

  get canStream(): boolean {
    if (this._streamIn === S_END || this._streamOut === S_END) return false;
    if (this._streamIn !== S_NEW || this._streamOut !== S_NEW) return true;
    const rem = this.remote;
    if (!(rem instanceof Msg)) return false;
    return rem._streamIn !== S_NEW || rem._streamOut !== S_NEW;
  }

  /** Factory for a call message. */
  static Call(cmd: Path | string, a: unknown[], kw: Record<string, unknown>, flags = 0): Msg {
    if (typeof cmd === 'string') {
      if (cmd.includes(':') || cmd.includes('.')) {
        throw new Error('Wrap command paths in a Path() call');
      }
      cmd = Path.build([cmd]);
    }
    const s = new Msg();
    s._cmd = cmd;
    s._a = a;
    s._kw = kw;
    if (flags & B_STREAM) {
      s._streamIn = S_ON;
    }
    return s;
  }

  /** Replace this message's remote with a link. */
  replaceWith(link: MsgLink): void {
    const rem = this._remote;
    if (rem === null) {
      link.setRemote(this);
      this._remote = link;
      return;
    }
    rem.setRemote(link); // this kills self
    link.setRemote(rem);
  }

  /** Store an incoming message and resolve the wait. */
  private _setMsg(a: unknown[], kw: OptKw, flags: number): void {
    if (flags & B_ERROR) {
      const err = decodeStreamError(a);
      this._result = { ok: false, error: err instanceof Error ? err : new StreamError(a) };
    } else {
      const realKw = kw ?? {};
      this._result = { ok: true, value: [a, realKw] };
    }
    if (this._resultResolve) {
      this._deliverResult();
    }
  }

  private _deliverResult(): void {
    const resolve = this._resultResolve;
    if (!resolve || !this._result) return;
    this._resultResolve = null;
    if (this._result.ok) {
      resolve(new MsgResult(this._result.value[0], this._result.value[1]));
    } else {
      // Reject the promise
      const reject = (this._resultReject as unknown as ((e: Error) => void) | null);
      if (reject) {
        this._resultReject = null;
        reject(this._result.error);
      }
    }
  }

  private _resultReject: ((e: Error) => void) | null = null;

  /** Wait for the (non-streamed) reply. Returns a MsgResult. */
  waitReplied(): Promise<MsgResult> {
    if (this._result) {
      if (this._result.ok) {
        return Promise.resolve(new MsgResult(this._result.value[0], this._result.value[1]));
      }
      return Promise.reject(this._result.error);
    }
    if (this._streamIn === S_END) {
      return Promise.reject(new Error('NoStream'));
    }
    if (!this._resultPromise) {
      this._resultPromise = new Promise<MsgResult>((resolve, reject) => {
        this._resultResolve = resolve;
        this._resultReject = reject;
      });
    }
    return this._resultPromise;
  }

  /** Receiver for data from the other side. */
  override async mlRecv(a: unknown[], kw: OptKw, flags: number): Promise<void> {
    if (this._streamIn === S_END) {
      // Late message
      if (!(flags & B_ERROR) || a.length !== 1 || a[0] !== E_CANCEL) {
        // Log late message
      }
      return;
    }

    if (!(flags & B_STREAM)) {
      // Out-of-band / final message
      this._setMsg(a, kw, flags);
      this._streamIn = S_END;
      if (this._streamOut === S_ON) {
        this._streamOut = S_OFF;
      }
    } else if (flags & B_ERROR) {
      // Warning (phase 2)
      const exc = decodeStreamError(a);
      if (exc instanceof Flow) {
        // Flow control — phase 2
      } else {
        this.warnings.push(exc instanceof Error ? exc : new StreamError(a));
      }
    } else if (this._streamIn === S_NEW) {
      // First streamed message (phase 2)
      this._setMsg(a, kw, flags);
      this._streamIn = S_ON;
    }
    // else: streamed data (phase 2)

    await this._ended();
  }

  override async mlSend(a: unknown[], kw: OptKw, flags: number): Promise<void> {
    if (this._streamOut === S_END) return;
    if (!(flags & B_STREAM)) {
      this._streamOut = S_END;
    } else {
      if (this._streamOut === S_NEW && !(flags & B_ERROR)) {
        this._streamOut = S_ON;
      }
    }
    await super.mlSend(a, kw, flags);
  }

  /** Send the result. */
  async result(...a: unknown[]): Promise<void> {
    const kw: Record<string, unknown> = {};
    if (this._remote === null) {
      // Local: store the result directly
      if (this._result) {
        throw new Error('Dup call');
      }
      this._result = { ok: true, value: [a, kw] };
      this._deliverResult();
      return;
    }
    await this.mlSend(a, kw, 0);
  }

  /** Send an error result. */
  async errorResult(...a: unknown[]): Promise<void> {
    await this.mlSend(a, null, B_ERROR);
  }

  /** Finalize if both directions are done. */
  private async _ended(): Promise<void> {
    if (this._streamIn !== S_END) return;
    if (this._streamOut !== S_END) return;
    await this.kill();
  }

  override toString(): string {
    return `<${this.constructor.name}:L${this.linkId} r=${this._remote ? `L${this._remote.linkId}` : '-'}: ${this._cmd ?? ''} ${JSON.stringify(this._a)} ${JSON.stringify(this._kw)}>`;
  }
}
