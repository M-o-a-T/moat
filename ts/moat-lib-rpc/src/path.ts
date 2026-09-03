/**
 * MoaT Path type — immutable, tag-39 encoded in CBOR.
 *
 * Mirrors the array form of moat/lib/path/_impl.py for wire compatibility.
 * Full Path string parsing (slash/dot notation) is stretch; the wire only
 * needs the array form.
 */

/** Elements that can appear in a Path. */
export type PathElem = string | number | bigint | boolean | null | Uint8Array | Path;

/**
 * Immutable Path backed by an array of elements.
 *
 * On the wire, Path *values* (in args/kw) are encoded as CBOR tag 39
 * (an array of elements). The command slot of a call's first message
 * is sent as a plain array (matching Python's bytes, §4.7 of PLAN.md).
 */
export class Path {
  private readonly _elements: readonly PathElem[];
  /** Optional root prefix (for RootPath semantics — phase 3). */
  readonly _prefix: string | null = null;

  constructor(elements: readonly PathElem[] = []) {
    this._elements = Object.freeze([...elements]);
  }

  /** Build a Path from various inputs. */
  static build(val: PathElem[] | Path | string, decoded = false): Path {
    if (val instanceof Path) return val;
    if (typeof val === 'string') {
      // Simple split on dots for basic string paths
      if (val === '') return new Path([]);
      return new Path(val.split('.'));
    }
    // Check for a leading root proxy (decoded=True)
    if (decoded && val.length > 0 && typeof val[0] === 'string' && val[0] === 'R') {
      const rest = val.slice(1);
      const p = new Path(rest);
      // Reflect the root prefix
      Object.defineProperty(p, '_prefix', { value: 'R', writable: false });
      return p;
    }
    return new Path(val);
  }

  /** Get the raw elements array. */
  get raw(): readonly PathElem[] {
    return this._elements;
  }

  /** Raw elements including root prefix if present (for encoding). */
  get rawRooted(): readonly PathElem[] {
    if (this._prefix) {
      return [this._prefix, ...this._elements];
    }
    return this._elements;
  }

  /** Length of the path. */
  get length(): number {
    return this._elements.length;
  }

  /** Get element at index. */
  get(index: number): PathElem | undefined {
    return this._elements[index];
  }

  /** Iterator. */
  *[Symbol.iterator](): Iterator<PathElem> {
    yield* this._elements;
  }

  /** Parent path (all but last element). */
  get parent(): Path {
    if (this._elements.length <= 1) return new Path([]);
    return new Path(this._elements.slice(0, -1));
  }

  /** Concatenate two paths. */
  concat(other: Path | PathElem[]): Path {
    const elems = other instanceof Path ? other.raw : other;
    return new Path([...this._elements, ...elems]);
  }

  /** Append a single element. */
  append(elem: PathElem): Path {
    return new Path([...this._elements, elem]);
  }

  /** String representation (dot-separated). */
  toString(): string {
    return this._elements
      .map((e) => {
        if (e === null) return ':n';
        if (typeof e === 'boolean') return e ? ':t' : ':f';
        if (typeof e === 'string') return e;
        if (typeof e === 'number' || typeof e === 'bigint') return String(e);
        if (e instanceof Uint8Array) return ':v' + Buffer.from(e).toString('hex');
        if (e instanceof Path) return e.toString();
        return String(e);
      })
      .join('.');
  }

  /** Reversed copy (used by command dispatch). */
  reverse(): PathElem[] {
    return [...this._elements].reverse();
  }

  /** Equality. */
  equals(other: Path): boolean {
    if (this.length !== other.length) return false;
    for (let i = 0; i < this.length; i++) {
      if (this._elements[i] !== other._elements[i]) return false;
    }
    return true;
  }

  /** Empty path singleton. */
  static EMPTY = new Path([]);

  /** Convert to plain array (for wire encoding). */
  toArray(): PathElem[] {
    return [...this._elements];
  }
}
