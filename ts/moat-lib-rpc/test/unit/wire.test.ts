import { describe, expect, it } from 'vitest';
import { i_f2wire, wire2i_f } from '../../src/wire.js';
import { B_WARNING_INTERNAL } from '../../src/const.js';

describe('wire header packing', () => {
  describe('i_f2wire (encode)', () => {
    it('packs id=1 flag=0 → 0', () => {
      expect(i_f2wire(1, 0)).toBe(0);
    });

    it('packs id=1 flag=1 → 1', () => {
      expect(i_f2wire(1, 1)).toBe(1);
    });

    it('packs id=2 flag=0 → 4', () => {
      expect(i_f2wire(2, 0)).toBe(4);
    });

    it('packs id=-1 flag=0 → -4 (reply to id=1)', () => {
      expect(i_f2wire(-1, 0)).toBe(-4);
    });

    it('packs id=-1 flag=2 (error) → -2', () => {
      expect(i_f2wire(-1, 2)).toBe(-2);
    });

    it('throws on id=0', () => {
      expect(() => i_f2wire(0, 0)).toThrow();
    });

    it('accepts flag=7 (B_WARNING_INTERNAL)', () => {
      expect(i_f2wire(1, 7)).toBe(3); // 7 & 3 = 3
    });

    it('handles large ids without 32-bit overflow', () => {
      // id > 2^29 would overflow with <<, but *4 is safe
      const bigId = 0x20000000; // 2^29
      const w = i_f2wire(bigId, 0);
      expect(w).toBe((bigId - 1) * 4);
    });
  });

  describe('wire2i_f (decode)', () => {
    it('decodes wire=0 → [1, 0]', () => {
      expect(wire2i_f(0)).toEqual([1, 0]);
    });

    it('decodes wire=4 → [2, 0]', () => {
      expect(wire2i_f(4)).toEqual([2, 0]);
    });

    it('decodes wire=-4 → [-1, 0]', () => {
      expect(wire2i_f(-4)).toEqual([-1, 0]);
    });

    it('decodes wire=-2 → [-1, 2]', () => {
      expect(wire2i_f(-2)).toEqual([-1, 2]);
    });

    it('decodes wire=1 → [1, 1] (stream flag)', () => {
      expect(wire2i_f(1)).toEqual([1, 1]);
    });

    it('decodes wire=3 → [1, 3] (warning flag)', () => {
      expect(wire2i_f(3)).toEqual([1, 3]);
    });
  });

  describe('round-trip', () => {
    it('originator id=1 flag=0 → wire 0 → decode [1,0] → flip to -1', () => {
      const w = i_f2wire(1, 0);
      expect(w).toBe(0);
      const [id, flag] = wire2i_f(w);
      expect(id).toBe(1);
      expect(flag).toBe(0);
      // Flip sign on receiving side
      expect(-id).toBe(-1);
    });

    it('reply id=-1 flag=0 → wire -4 → decode [-1,0] → flip to 1', () => {
      const w = i_f2wire(-1, 0);
      expect(w).toBe(-4);
      const [id, flag] = wire2i_f(w);
      expect(id).toBe(-1);
      expect(flag).toBe(0);
      expect(-id).toBe(1);
    });

    it('round-trips various ids and flags', () => {
      for (const id of [1, 2, 3, 5, 10, 63, 64, 100, 1000, -1, -2, -5, -100]) {
        for (const flag of [0, 1, 2, 3]) {
          const w = i_f2wire(id, flag);
          const [decId, decFlag] = wire2i_f(w);
          expect(decId).toBe(id);
          expect(decFlag).toBe(flag);
        }
      }
    });
  });
});
