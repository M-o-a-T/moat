import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { i_f2wire, wire2i_f } from '../../src/wire.js';

describe('property: wire header packing', () => {
  it('round-trips (id, flag) → wire → decode for positive ids', () => {
    fc.assert(
      fc.property(fc.integer({ min: 1, max: 100000 }), fc.integer({ min: 0, max: 3 }), (id, flag) => {
        const w = i_f2wire(id, flag);
        const [decId, decFlag] = wire2i_f(w);
        expect(decId).toBe(id);
        expect(decFlag).toBe(flag);
      }),
    );
  });

  it('round-trips for negative ids (responder replies)', () => {
    fc.assert(
      fc.property(fc.integer({ min: -100000, max: -1 }), fc.integer({ min: 0, max: 3 }), (id, flag) => {
        const w = i_f2wire(id, flag);
        const [decId, decFlag] = wire2i_f(w);
        expect(decId).toBe(id);
        expect(decFlag).toBe(flag);
      }),
    );
  });

  it('never produces id=0 on decode (id=0 is never sent)', () => {
    fc.assert(
      fc.property(fc.integer({ min: -100000, max: 100000 }).filter((n) => n !== 0), fc.integer({ min: 0, max: 3 }), (id, flag) => {
        const w = i_f2wire(id, flag);
        const [decId] = wire2i_f(w);
        expect(decId).not.toBe(0);
      }),
    );
  });

  it('flag extraction is always in [0,3] on the wire', () => {
    fc.assert(
      fc.property(fc.integer({ min: -100000, max: 100000 }).filter((n) => n !== 0), fc.integer({ min: 0, max: 3 }), (id, flag) => {
        const w = i_f2wire(id, flag);
        const [, decFlag] = wire2i_f(w);
        expect(decFlag).toBeGreaterThanOrEqual(0);
        expect(decFlag).toBeLessThanOrEqual(3);
      }),
    );
  });
});
