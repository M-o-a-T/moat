/**
 * Property/fuzz tests — random message sequences through the sans-IO core.
 *
 * Generates random RPC calls, feeds them through the core, drains the
 * outbound messages, and verifies invariants hold throughout.
 */

import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { RpcCore } from '../../src/core/handler.js';
import { encodeMoat, decodeMoat } from '../../src/codec.js';
import { i_f2wire, wire2i_f } from '../../src/wire.js';
import { IncrementalDecoder } from '../../src/transport/framing.js';
import {
  B_STREAM,
  B_ERROR,
  E_CANCEL,
  E_NO_STREAM,
  E_ERROR,
  E_UNSPEC,
  E_SKIP,
} from '../../src/const.js';

describe('property: random message sequences through the core', () => {
  it('arbitrary sequence of calls produces unique IDs', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            cmd: fc.string({ minLength: 1, maxLength: 20 }),
            args: fc.array(fc.oneof(fc.integer(), fc.string(), fc.boolean())),
          }),
          { minLength: 1, maxLength: 50 },
        ),
        (sequence) => {
          const core = new RpcCore(null, {});
          const seenIds = new Set<number>();

          for (const { cmd, args } of sequence) {
            const { link } = core.call(cmd, [...args], {});
            expect(seenIds.has(link.id)).toBe(false);
            seenIds.add(link.id);
          }

          // Total distinct IDs should equal the sequence length
          expect(seenIds.size).toBe(sequence.length);
        },
      ),
      { numRuns: 50 },
    );
  });

  it('feed/drain round-trip preserves message structure', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            cmd: fc.string({ minLength: 1, maxLength: 10 }).filter((s) => !s.includes('.') && !s.includes(':')),
            args: fc.array(fc.oneof(fc.integer({ min: -1000, max: 1000 }), fc.string({ maxLength: 20 }))),
          }),
          { minLength: 1, maxLength: 10 },
        ),
        (sequence) => {
          const core = new RpcCore(null, {});

          // Make calls and drain outbound
          const calls: { id: number; cmd: string; args: unknown[] }[] = [];
          for (const { cmd, args } of sequence) {
            const { link } = core.call(cmd, [...args], {});
            calls.push({ id: link.id, cmd, args: [...args] });
          }

          const outbound = core.drain();
          expect(outbound.length).toBe(sequence.length);

          // Each outbound message should have the correct wire header
          for (let i = 0; i < outbound.length; i++) {
            const msg = outbound[i]!;
            const expectedWire = i_f2wire(calls[i]!.id, 0);
            expect(msg.wire).toBe(expectedWire);

            // Payload should be [wire, [cmd], *args]
            const payload = msg.payload;
            expect(payload[0]).toBe(expectedWire);
            expect(payload[1]).toEqual([calls[i]!.cmd]);
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it('feeding back responses resolves all pending calls', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            cmd: fc.string({ minLength: 1, maxLength: 10 }).filter((s) => !s.includes('.') && !s.includes(':')),
            result: fc.oneof(fc.integer(), fc.string({ maxLength: 20 }), fc.boolean(), fc.constant(null)),
          }),
          { minLength: 1, maxLength: 20 },
        ),
        (sequence) => {
          const core = new RpcCore(null, {});

          // Make calls
          const msgs: { id: number; msg: import('../../src/core/msg.js').Msg }[] = [];
          for (const { cmd } of sequence) {
            const { link, msg } = core.call(cmd, [], {});
            msgs.push({ id: link.id, msg });
          }
          core.drain(); // flush outbound

          // Feed back responses
          for (let i = 0; i < sequence.length; i++) {
            const { id } = msgs[i]!;
            const { result } = sequence[i]!;
            const replyWire = i_f2wire(-id, 0);
            core.feed([replyWire, [result]]);
          }

          // All should have results
          for (const { msg } of msgs) {
            expect(msg.hasResult).toBe(true);
            expect(msg.isError).toBe(false);
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it('feeding back error responses resolves all pending calls as errors', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            cmd: fc.string({ minLength: 1, maxLength: 10 }).filter((s) => !s.includes('.') && !s.includes(':')),
            errorCode: fc.constantFrom(E_CANCEL, E_NO_STREAM, E_ERROR, E_UNSPEC, E_SKIP),
          }),
          { minLength: 1, maxLength: 20 },
        ),
        (sequence) => {
          const core = new RpcCore(null, {});

          // Make calls
          const msgs: { id: number; msg: import('../../src/core/msg.js').Msg }[] = [];
          for (const { cmd } of sequence) {
            const { link, msg } = core.call(cmd, [], {});
            msgs.push({ id: link.id, msg });
          }
          core.drain();

          // Feed back error responses
          for (let i = 0; i < sequence.length; i++) {
            const { id } = msgs[i]!;
            const { errorCode } = sequence[i]!;
            const replyWire = i_f2wire(-id, B_ERROR);
            core.feed([replyWire, [errorCode]]);
          }

          // All should have error results
          for (const { msg } of msgs) {
            expect(msg.hasResult).toBe(true);
            expect(msg.isError).toBe(true);
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it('mixed success and error responses resolve correctly', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            cmd: fc.string({ minLength: 1, maxLength: 10 }).filter((s) => !s.includes('.') && !s.includes(':')),
            isError: fc.boolean(),
            result: fc.oneof(fc.integer(), fc.string({ maxLength: 20 })),
            errorCode: fc.constantFrom(E_CANCEL, E_NO_STREAM, E_ERROR),
          }),
          { minLength: 2, maxLength: 30 },
        ),
        (sequence) => {
          const core = new RpcCore(null, {});

          const msgs: { id: number; msg: import('../../src/core/msg.js').Msg; isError: boolean }[] = [];
          for (const { cmd, isError } of sequence) {
            const { link, msg } = core.call(cmd, [], {});
            msgs.push({ id: link.id, msg, isError });
          }
          core.drain();

          for (let i = 0; i < sequence.length; i++) {
            const { id } = msgs[i]!;
            const { isError, result, errorCode } = sequence[i]!;
            if (isError) {
              core.feed([i_f2wire(-id, B_ERROR), [errorCode]]);
            } else {
              core.feed([i_f2wire(-id, 0), [result]]);
            }
          }

          for (const { msg, isError } of msgs) {
            expect(msg.hasResult).toBe(true);
            expect(msg.isError).toBe(isError);
          }
        },
      ),
      { numRuns: 50 },
    );
  });
});

describe('property: deep codec fuzzing', () => {
  it('round-trips deeply nested arrays', () => {
    fc.assert(
      fc.property(
        fc.array(fc.array(fc.array(fc.oneof(fc.integer(), fc.string(), fc.boolean())))),
        (nested) => {
          const encoded = encodeMoat(nested);
          const decoded = decodeMoat(encoded);
          expect(decoded).toEqual(nested);
        },
      ),
      { numRuns: 50 },
    );
  });

  it('round-trips objects with nested structures', () => {
    fc.assert(
      fc.property(
        fc.record({
          name: fc.string(),
          values: fc.array(fc.integer()),
          nested: fc.record({
            a: fc.boolean(),
            b: fc.string(),
          }),
        }),
        (obj) => {
          const encoded = encodeMoat(obj);
          const decoded = decodeMoat(encoded);
          expect(decoded).toEqual(obj);
        },
      ),
      { numRuns: 50 },
    );
  });

  it('round-trips wire messages with random headers and payloads', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 1000 }),
        fc.integer({ min: 0, max: 3 }),
        fc.array(fc.oneof(fc.integer(), fc.string({ maxLength: 50 }), fc.boolean(), fc.constant(null))),
        (id, flag, payload) => {
          const header = i_f2wire(id, flag);
          const wireMsg = [header, ...payload];
          const encoded = encodeMoat(wireMsg);
          const decoded = decodeMoat(encoded) as unknown[];
          expect(decoded[0]).toBe(header);
          // Payload elements should match (accounting for CBOR null/undefined)
          for (let i = 0; i < payload.length; i++) {
            const expected = payload[i];
            const actual = decoded[i + 1];
            if (expected === null) {
              expect(actual).toBeNull();
            } else if (typeof expected === 'number') {
              expect(actual).toBe(expected);
            } else if (typeof expected === 'string') {
              expect(actual).toBe(expected);
            } else if (typeof expected === 'boolean') {
              expect(actual).toBe(expected);
            }
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it('encoder produces deterministic output (same input → same bytes)', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.integer(),
          fc.string(),
          fc.boolean(),
          fc.array(fc.integer()),
          fc.record({ a: fc.integer(), b: fc.string() }),
        ),
        (value) => {
          const encoded1 = encodeMoat(value);
          const encoded2 = encodeMoat(value);
          expect(encoded1).toEqual(encoded2);
        },
      ),
      { numRuns: 50 },
    );
  });

  it('decoded-then-reencoded produces identical bytes (canonical CBOR)', () => {
    fc.assert(
      fc.property(
        fc.array(fc.oneof(fc.integer(), fc.string(), fc.boolean(), fc.constant(null))),
        (arr) => {
          const encoded1 = encodeMoat(arr);
          const decoded = decodeMoat(encoded1);
          const encoded2 = encodeMoat(decoded);
          expect(encoded2).toEqual(encoded1);
        },
      ),
      { numRuns: 50 },
    );
  });
});

describe('property: incremental decoder robustness', () => {
  it('splitting CBOR data at arbitrary positions still decodes correctly', () => {
    fc.assert(
      fc.property(
        // Wire messages are always arrays — simulate real wire traffic
        fc.array(
          fc.array(fc.oneof(fc.integer({ min: -1000, max: 1000 }), fc.string({ maxLength: 20 }), fc.boolean())),
          { minLength: 1, maxLength: 5 },
        ),
        fc.integer({ min: 1, max: 10 }),
        (messages, splitSize) => {
          // Encode each array message individually, concatenate
          const encodedParts = messages.map((m) => encodeMoat(m));
          const totalLen = encodedParts.reduce((acc, e) => acc + e.length, 0);
          const allBytes = new Uint8Array(totalLen);
          let offset = 0;
          for (const encoded of encodedParts) {
            allBytes.set(encoded, offset);
            offset += encoded.length;
          }

          // Feed in small chunks to the IncrementalDecoder
          const decoder = new IncrementalDecoder();
          for (let i = 0; i < allBytes.length; i += splitSize) {
            const chunk = allBytes.subarray(i, Math.min(i + splitSize, allBytes.length));
            decoder.feed(new Uint8Array(chunk));
          }

          const decoded = decoder.drain();
          expect(decoded.length).toBe(messages.length);

          // Verify each decoded message matches the original
          for (let i = 0; i < decoded.length; i++) {
            expect(decoded[i]).toEqual(messages[i]);
          }
        },
      ),
      { numRuns: 30 },
    );
  });
});
