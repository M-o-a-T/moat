/**
 * Header integer packing for the MoaT RPC wire protocol.
 *
 * Mirrors i_f2wire / wire2i_f from moat/lib/rpc/stream/base.py.
 *
 * Uses bitwise shifts exactly as Python does: (id << 2) | (flag & 3)
 * and w >> 2. IDs are recycled, so the number of in-flight requests
 * stays small — JS 32-bit shift overflow (> 2^29) is never reached.
 */

import { B_WARNING_INTERNAL } from './const.js';

/**
 * Encode (id, flag) into the wire header integer.
 *
 * @param id - The sub-channel id. Must not be 0.
 *            Positive ids are allocated by the originator (≥ 1).
 *            Negative ids are used by the responder in replies.
 * @param flag - The flag bits (0..3, or 7 for B_WARNING_INTERNAL).
 * @returns The packed wire integer.
 */
export function i_f2wire(id: number, flag: number): number {
  if (id === 0) throw new AssertionError('id must not be 0');
  if (!(flag >= 0 && flag <= 3) && flag !== B_WARNING_INTERNAL) {
    throw new AssertionError(`invalid flag ${flag}`);
  }
  if (id > 0) id -= 1;
  return (id << 2) | (flag & 3);
}

/**
 * Decode a wire header integer into (id, flag).
 *
 * @param w - The wire integer.
 * @returns Tuple [id, flag]. The caller then flips the sign: i = -i.
 */
export function wire2i_f(w: number): [number, number] {
  // Python: f = w & 3; id = w >> 2; if id >= 0: id += 1
  const f = w & 3;
  let id = w >> 2;
  if (id >= 0) id += 1;
  return [id, f];
}

/** Round-trip helper for testing. */
export function roundtrip(id: number, flag: number): [number, number] {
  const w = i_f2wire(id, flag);
  return wire2i_f(w);
}

class AssertionError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'AssertionError';
  }
}
