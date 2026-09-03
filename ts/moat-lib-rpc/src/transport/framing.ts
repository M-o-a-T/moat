/**
 * Incremental CBOR decoder for TCP/pipe streams.
 *
 * Raw byte streams can split a single message across reads or coalesce
 * several messages into one. CBOR is self-delimiting, so we scan the byte
 * length of each top-level item, slice it off, and decode it with the
 * MoaT tag table — repeating until the buffer holds no complete item.
 */

import { decodeMessage } from '../codec.js';

/**
 * IncrementalDecoder — accumulates bytes and yields complete decoded
 * CBOR messages, tolerating split and coalesced reads.
 */
export class IncrementalDecoder {
  private _buffer: Uint8Array = new Uint8Array(0);
  private _decoded: unknown[] = [];

  /** Feed raw bytes. Decodes every complete CBOR item now available. */
  feed(data: Uint8Array): void {
    if (data.length === 0) return;
    if (this._buffer.length === 0) {
      this._buffer = data.slice();
    } else {
      const combined = new Uint8Array(this._buffer.length + data.length);
      combined.set(this._buffer, 0);
      combined.set(data, this._buffer.length);
      this._buffer = combined;
    }

    // Drain every complete top-level item.
    for (;;) {
      const len = scanItemLength(this._buffer, 0);
      if (len === null) break; // incomplete — wait for more bytes
      const slice = this._buffer.subarray(0, len);
      this._decoded.push(decodeMessage(slice));
      if (len >= this._buffer.length) {
        this._buffer = new Uint8Array(0);
        break;
      }
      this._buffer = this._buffer.subarray(len);
    }
  }

  /** Get decoded messages. */
  drain(): unknown[] {
    const result = this._decoded;
    this._decoded = [];
    return result;
  }

  /** Clear the buffer. */
  clear(): void {
    this._buffer = new Uint8Array(0);
    this._decoded = [];
  }
}

/**
 * Compute the byte length of the single CBOR item starting at ``off``.
 *
 * Returns the length, or ``null`` if the buffer doesn't yet contain the
 * whole item (the caller should wait for more bytes). Only definite-length
 * items are supported — the MoaT codecs never emit indefinite-length CBOR.
 */
function scanItemLength(buf: Uint8Array, off: number): number | null {
  const end = buf.length;
  if (off >= end) return null;
  const first = buf[off]!;
  const mt = first >> 5;
  const ai = first & 0x1f;

  let hl: number;
  if (ai < 24) {
    hl = 1;
  } else if (ai === 24) {
    if (off + 2 > end) return null;
    hl = 2;
  } else if (ai === 25) {
    if (off + 3 > end) return null;
    hl = 3;
  } else if (ai === 26) {
    if (off + 5 > end) return null;
    hl = 5;
  } else if (ai === 27) {
    if (off + 9 > end) return null;
    hl = 9;
  } else {
    // ai === 31: indefinite-length / BREAK — unsupported.
    throw new Error('Indefinite-length CBOR is not supported');
  }

  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const readCount = (): number => {
    if (ai < 24) return ai;
    if (ai === 24) return dv.getUint8(off + 1);
    if (ai === 25) return dv.getUint16(off + 1, false);
    if (ai === 26) return dv.getUint32(off + 1, false);
    // ai === 27: counts beyond 2^53 are nonsensical for item counts.
    return Number(dv.getBigUint64(off + 1, false));
  };

  switch (mt) {
    case 0: // unsigned int
    case 1: // negative int
      return hl;
    case 2: // byte string
    case 3: { // text string
      const n = readCount();
      if (off + hl + n > end) return null;
      return hl + n;
    }
    case 4: { // array
      const n = readCount();
      let pos = off + hl;
      for (let i = 0; i < n; i++) {
        const il = scanItemLength(buf, pos);
        if (il === null) return null;
        pos += il;
      }
      return pos - off;
    }
    case 5: { // map
      const n = readCount();
      let pos = off + hl;
      for (let i = 0; i < 2 * n; i++) {
        const il = scanItemLength(buf, pos);
        if (il === null) return null;
        pos += il;
      }
      return pos - off;
    }
    case 6: { // tag
      const il = scanItemLength(buf, off + hl);
      if (il === null) return null;
      return hl + il;
    }
    case 7: // simple / float / break
      return hl;
    default:
      throw new Error(`Invalid CBOR major type ${mt}`);
  }
}
