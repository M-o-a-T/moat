import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { encodeMoat, decodeMoat } from '../../src/codec.js';

describe('property: codec round-trips', () => {
  it('round-trips arbitrary integers', () => {
    fc.assert(
      fc.property(fc.integer(), (n) => {
        expect(decodeMoat(encodeMoat(n))).toBe(n);
      }),
    );
  });

  it('round-trips arbitrary strings', () => {
    fc.assert(
      fc.property(fc.string(), (s) => {
        expect(decodeMoat(encodeMoat(s))).toBe(s);
      }),
    );
  });

  it('round-trips arbitrary booleans', () => {
    fc.assert(
      fc.property(fc.boolean(), (b) => {
        expect(decodeMoat(encodeMoat(b))).toBe(b);
      }),
    );
  });

  it('round-trips arrays of mixed primitives', () => {
    fc.assert(
      fc.property(
        fc.array(fc.oneof(fc.integer(), fc.string(), fc.boolean(), fc.constant(null))),
        (arr) => {
          const decoded = decodeMoat(encodeMoat(arr));
          expect(decoded).toEqual(arr);
        },
      ),
    );
  });

  it('round-trips objects with string keys and primitive values', () => {
    fc.assert(
      fc.property(
        fc.record({
          a: fc.integer(),
          b: fc.string(),
          c: fc.boolean(),
        }),
        (obj) => {
          const decoded = decodeMoat(encodeMoat(obj));
          expect(decoded).toEqual(obj);
        },
      ),
    );
  });
});
