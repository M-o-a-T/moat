/**
 * Error classes for the MoaT RPC protocol.
 *
 * Mirrors moat/lib/rpc/errors.py.
 */

import {
  E_CANCEL,
  E_ERROR,
  E_MUST_STREAM,
  E_NO_CMD,
  E_NO_CMDS,
  E_NO_STREAM,
  E_SKIP,
  E_UNSPEC,
} from './const.js';

/** Sentinel: not given / undefined. Maps to CBOR undefined (0xF7). */
export const NotGiven = Symbol('NotGiven');

/** Flow control indication (not a thrown error). */
export class Flow {
  constructor(public n: number) {}
}

/** Base class for all RPC stream errors. */
export class StreamError extends Error {
  /** The raw message payload. */
  msg: unknown[];

  constructor(msg: unknown[] = []) {
    super();
    this.msg = msg;
  }

  override toString(): string {
    return `${this.constructor.name}: ${JSON.stringify(this.msg)}`;
  }
}

/** Unspecified stop. */
export class StopMe extends StreamError {}

/** Data skipped, took too long. */
export class SkippedData extends StreamError {}

/** No streaming support. */
export class NoStream extends StreamError {}

/** No support for any commands. */
export class NoCmds extends StreamError {}

/** Unknown command. */
export class NoCmd extends StreamError {
  constructor(msg: unknown[], public depth: number) {
    super(msg);
  }
}

/** API: NoStream called on a streaming endpoint. */
export class WantsStream extends StreamError {}

/** Requires streaming support. */
export class MustStream extends StreamError {}

/** Some remote error that is not proxied. */
export class RemoteError extends StreamError {}

/** An element of the command path was not ready. */
export class NotReadyError extends Error {}

/** The command path was too short. */
export class ShortCommandError extends Error {}

/** The command path was too long. */
export class LongCommandError extends Error {}

/** Cancellation propagated from the remote side. */
export class CancelledError extends StreamError {}

/** EOF on the transport. */
export class EOFError extends Error {
  constructor(msg = 'EOF') {
    super(msg);
    this.name = 'EOFError';
  }
}

/**
 * Decode a stream-error payload into the appropriate error type.
 * This mirrors StreamError.__new__ in Python.
 *
 * Unlike the StreamError constructor (which in Python uses __new__
 * to return a different class), this factory function creates the
 * correct subclass based on the payload.
 */
export function decodeStreamError(msg: unknown[]): Error | Flow {
  if (msg.length !== 1) {
    return new StreamError(msg);
  }
  const m = msg[0]!;
  if (typeof m === 'number') {
    if (m >= 0) return new Flow(m);
    if (m === E_UNSPEC) return new StopMe(msg);
    if (m === E_NO_STREAM) return new NoStream(msg);
    if (m === E_MUST_STREAM) return new MustStream(msg);
    if (m === E_SKIP) return new SkippedData(msg);
    if (m === E_NO_CMDS) return new NoCmds(msg);
    if (m === E_CANCEL) return new CancelledError(msg);
    if (m === E_ERROR) return new RemoteError(msg);
    if (m <= E_NO_CMD) return new NoCmd(msg, E_NO_CMD - m);
    return new StreamError(msg);
  }
  if (m instanceof Error) return m;
  return new StreamError(msg);
}
