/**
 * Incremental CBOR decoder helper for TCP streams.
 *
 * Feeds bytes to cbor2's streaming decoder and extracts one
 * decoded array at a time. No msg_prefix handling.
 */

import { decode } from 'cbor2';

/**
 * IncrementalDecoder — accumulates bytes and yields complete CBOR objects.
 *
 * CBOR is self-delimiting; we try to decode from the start of the buffer
 * and advance past each complete object.
 */
export class IncrementalDecoder {
  private _buffer: Uint8Array = new Uint8Array(0);
  private _decoded: unknown[] = [];

  /** Feed raw bytes. Attempts to decode complete CBOR objects. */
  feed(data: Uint8Array): void {
    // Append to buffer
    const combined = new Uint8Array(this._buffer.length + data.length);
    combined.set(this._buffer, 0);
    combined.set(data, this._buffer.length);
    this._buffer = combined;

    // Try to decode complete objects from the buffer
    while (this._buffer.length > 0) {
      try {
        const value = decode(this._buffer);
        this._decoded.push(value);
        // We don't know exactly how many bytes were consumed.
        // For phase 1, we consume the entire buffer (works for one message per read).
        // Phase 2 will use cbor2's saveOriginal/getEncodedLength for proper framing.
        this._buffer = new Uint8Array(0);
        break;
      } catch {
        // Incomplete data — wait for more
        break;
      }
    }
  }

  /** Get decoded objects. */
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
