import { describe, expect, it } from 'vitest';
import { encodeMoat, decodeMoat } from '../../src/codec.js';
import { Path } from '../../src/path.js';
import { Tag } from 'cbor2';

describe('codec', () => {
  describe('basic round-trips', () => {
    it('round-trips a simple integer', () => {
      const buf = encodeMoat(42);
      expect(decodeMoat(buf)).toBe(42);
    });

    it('round-trips a string', () => {
      const buf = encodeMoat('hello world');
      expect(decodeMoat(buf)).toBe('hello world');
    });

    it('round-trips a boolean', () => {
      expect(decodeMoat(encodeMoat(true))).toBe(true);
      expect(decodeMoat(encodeMoat(false))).toBe(false);
    });

    it('round-trips null', () => {
      expect(decodeMoat(encodeMoat(null))).toBe(null);
    });

    it('round-trips undefined', () => {
      expect(decodeMoat(encodeMoat(undefined))).toBe(undefined);
    });

    it('round-trips an array', () => {
      const arr = [1, 'two', true, null];
      const decoded = decodeMoat(encodeMoat(arr));
      expect(decoded).toEqual(arr);
    });

    it('round-trips a simple object', () => {
      const obj = { a: 1, b: 'two' };
      const decoded = decodeMoat(encodeMoat(obj));
      expect(decoded).toEqual(obj);
    });
  });

  describe('MoaT extension tags', () => {
    it('encodes/decodes Path as tag 39', () => {
      const path = Path.build(['foo', 'bar', 'baz']);
      const buf = encodeMoat(path);
      const decoded = decodeMoat(buf);
      expect(decoded).toBeInstanceOf(Path);
      expect((decoded as Path).length).toBe(3);
      expect((decoded as Path).get(0)).toBe('foo');
    });

    it('encodes/decodes Set as tag 258', () => {
      const s = new Set([1, 2, 3]);
      const buf = encodeMoat(s);
      const decoded = decodeMoat(buf);
      expect(decoded).toBeInstanceOf(Set);
      expect((decoded as Set<unknown>).size).toBe(3);
    });

    it('encodes/decodes Date as tag 1 (epoch)', () => {
      const date = new Date('2024-01-15T12:00:00Z');
      const buf = encodeMoat(date);
      const decoded = decodeMoat(buf);
      expect(decoded).toBeInstanceOf(Date);
      expect((decoded as Date).getTime()).toBe(date.getTime());
    });

    it('decodes tag 0 (ISO date string)', () => {
      // Manually create a tag-0 CBOR value
      const buf = encodeMoat(new Tag(0, '2024-01-15T12:00:00Z'));
      const decoded = decodeMoat(buf);
      expect(decoded).toBeInstanceOf(Date);
    });
  });

  describe('RPC message arrays', () => {
    it('encodes/decodes a simple call message [0, ["ping"]]', () => {
      const msg = [0, ['ping']];
      const decoded = decodeMoat(encodeMoat(msg));
      expect(decoded).toEqual(msg);
    });

    it('encodes/decodes a reply message [-4, ["pong"]]', () => {
      const msg = [-4, ['pong']];
      const decoded = decodeMoat(encodeMoat(msg));
      expect(decoded).toEqual(msg);
    });

    it('encodes/decodes an error message [-6, [-3]]', () => {
      const msg = [-6, [-3]]; // E_CANCEL
      const decoded = decodeMoat(encodeMoat(msg));
      expect(decoded).toEqual(msg);
    });

    it('encodes/decodes a message with kwargs', () => {
      const msg = [0, ['cmd'], { key: 'value' }];
      const decoded = decodeMoat(encodeMoat(msg));
      expect(decoded).toEqual(msg);
    });
  });

  describe('bytes vs text', () => {
    it('preserves Uint8Array as bytes', () => {
      const data = new Uint8Array([1, 2, 3, 4, 5]);
      const decoded = decodeMoat(encodeMoat(data));
      expect(decoded).toBeInstanceOf(Uint8Array);
      expect(decoded).toEqual(data);
    });
  });
});
