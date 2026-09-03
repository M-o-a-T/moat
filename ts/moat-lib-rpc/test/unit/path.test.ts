import { describe, expect, it } from 'vitest';
import { Path } from '../../src/path.js';

describe('Path', () => {
  it('creates from elements', () => {
    const p = Path.build(['a', 'b', 'c']);
    expect(p.length).toBe(3);
    expect(p.get(0)).toBe('a');
    expect(p.get(1)).toBe('b');
    expect(p.get(2)).toBe('c');
  });

  it('creates from string (dot-separated)', () => {
    const p = Path.build('a.b.c');
    expect(p.length).toBe(3);
    expect(p.get(0)).toBe('a');
  });

  it('creates empty path', () => {
    const p = Path.build('');
    expect(p.length).toBe(0);
  });

  it('concatenates paths', () => {
    const p1 = Path.build(['a', 'b']);
    const p2 = Path.build(['c', 'd']);
    const p3 = p1.concat(p2);
    expect(p3.length).toBe(4);
    expect(p3.get(2)).toBe('c');
  });

  it('gets parent', () => {
    const p = Path.build(['a', 'b', 'c']);
    const parent = p.parent;
    expect(parent.length).toBe(2);
    expect(parent.get(0)).toBe('a');
  });

  it('reverses', () => {
    const p = Path.build(['a', 'b', 'c']);
    const rev = p.reverse();
    expect(rev).toEqual(['c', 'b', 'a']);
  });

  it('converts to string', () => {
    const p = Path.build(['foo', 'bar']);
    expect(p.toString()).toBe('foo.bar');
  });

  it('compares for equality', () => {
    const p1 = Path.build(['a', 'b']);
    const p2 = Path.build(['a', 'b']);
    const p3 = Path.build(['a', 'c']);
    expect(p1.equals(p2)).toBe(true);
    expect(p1.equals(p3)).toBe(false);
  });

  it('iterates', () => {
    const p = Path.build(['x', 'y', 'z']);
    const elems: unknown[] = [];
    for (const e of p) {
      elems.push(e);
    }
    expect(elems).toEqual(['x', 'y', 'z']);
  });

  it('appends an element', () => {
    const p = Path.build(['a']).append('b');
    expect(p.length).toBe(2);
    expect(p.get(1)).toBe('b');
  });

  it('handles decoded root prefix', () => {
    const p = Path.build(['R', 'a', 'b'], true);
    expect(p.length).toBe(2);
    expect(p.get(0)).toBe('a');
  });
});
