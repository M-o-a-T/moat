/**
 * Constants for the MoaT RPC wire protocol.
 *
 * Mirrors moat/lib/rpc/const.py.
 */

// --- Bitfield flags (low 2 bits of the header integer) ---

/** Final message for this direction (out-of-band). */
export const B_STREAM = 1;
/** Terminal error (stream bit clear). */
export const B_ERROR = 2;
/** Warning / OOB info (= B_STREAM | B_ERROR). */
export const B_WARNING = 3;
/** Internal flow-control warning (reconstructed on decode, not transmitted distinctly). */
export const B_WARNING_INTERNAL = 7;

/** Flag string representation for logging. */
export const B_FLAGSTR = ' SEW';

// --- Error codes ---

export const E_UNSPEC = -1;
export const E_NO_STREAM = -2;
export const E_CANCEL = -3;
export const E_NO_CMDS = -4;
export const E_SKIP = -5;
export const E_MUST_STREAM = -6;
export const E_ERROR = -7;
export const E_NO_CMD = -11;

// --- Stream states (separate for in/out) ---

/** Terminal: stream-bit-clear message has been sent/received. */
export const S_END = 3;
/** No incoming message yet. */
export const S_NEW = 4;
/** We're streaming (seen/sent first message). */
export const S_ON = 5;
/** In: we don't want streaming and signalled NO. */
export const S_OFF = 6;

// --- Stream directions ---

export const SD_NONE = 0;
export const SD_IN = 1;
export const SD_OUT = 2;
export const SD_BOTH = 3;

/** Stringify message flags for logging. */
export function bFlName(flag: number): string {
  if (flag & B_ERROR) {
    return flag & B_STREAM ? '.W' : '.E';
  }
  return flag & B_STREAM ? '.S' : '';
}

/** Stringify message errors for logging. */
export function bErrName(err: unknown): string {
  if (typeof err !== 'number') return String(err);
  if (err >= 0) return `S+${err}`;
  if (err <= E_NO_CMD) return `NO_CMD_${-E_NO_CMD - err}`;
  if (err === E_UNSPEC) return 'UNSPEC';
  if (err === E_NO_STREAM) return 'NO_STREAM';
  if (err === E_CANCEL) return 'CANCEL';
  if (err === E_NO_CMDS) return 'NO_CMDS';
  if (err === E_SKIP) return 'SKIP';
  if (err === E_ERROR) return 'ERROR';
  return `?${err}`;
}
