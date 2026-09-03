/**
 * CBOR codec with MoaT extension tags.
 *
 * Uses the `cbor2` npm package (RFC 8949) with custom Tag handling
 * mirroring moat/lib/codec/_moat_cbor.py.
 *
 * Tag table:
 *   39     → Path (array of elements)
 *   27     → DProxy / wrapped object / error ([name, *args, ?kw])
 *   32769  → Proxy (by name, string/int)
 *   258    → Set (array)
 *   1      → Date (epoch seconds, float)
 *   0      → Date (ISO string, decode only)
 *   2/3    → bignum / neg-bignum (byte string)
 *   55799  → self-describe CBOR (passthrough)
 */

import { Tag, encode, decode, TypeEncoderMap } from 'cbor2';
import { Path } from './path.js';
import {
  DProxy,
  Proxy,
  encodeError,
  unwrapObj,
  decodeProxy,
  asProxy,
  name2obj,
  pushKw,
  popKw,
} from './proxy.js';

// --- Build the type encoder map ---

const typeEncoders = new TypeEncoderMap();

// Path → tag 39 [elements...]
typeEncoders.registerEncoder(Path, (obj: Path) => {
  return [39, obj.rawRooted];
});

// DProxy → tag 27 [name, *args, ?kw]
typeEncoders.registerEncoder(DProxy, (obj: DProxy) => {
  const res: unknown[] = [obj.name, ...obj.a];
  if (Object.keys(obj.k).length > 0 || (res.length > 0 && isPlainObject(res[res.length - 1]))) {
    res.push(obj.k);
  }
  return [27, res];
});

// Proxy → tag 32769 (name)
typeEncoders.registerEncoder(Proxy, (obj: Proxy) => {
  return [32769, obj.name];
});

// Set → tag 258 [elements...]
typeEncoders.registerEncoder(Set, (obj: Set<unknown>) => {
  return [258, Array.from(obj)];
});

// Error → tag 32769 (registered name) or tag 27 ["_rErr", className, ...args]
typeEncoders.registerEncoder(Error, (obj: Error) => {
  const result = encodeError(obj);
  if (result) {
    return result; // [tag, value]
  }
  return [32769, 'RemoteError'];
});

// --- Build the decode tag map ---

const tagDecoders = new Map<number, (value: unknown) => unknown>();

// Helper: unwrap a Tag to get its contents, or pass through if not a Tag
function tagContents(val: unknown): unknown {
  if (val instanceof Tag) {
    return val.contents;
  }
  return val;
}

// Tag 39: Path
tagDecoders.set(39, (val: unknown) => {
  const contents = tagContents(val);
  if (contents instanceof Array) {
    return Path.build(contents, true);
  }
  return new Tag(39, val);
});

// Tag 27: DProxy / wrapped object
tagDecoders.set(27, (val: unknown) => {
  const contents = tagContents(val);
  if (!(contents instanceof Array) || contents.length === 0) {
    return new Tag(27, val);
  }
  // Check if first element is a tag (nested proxy)
  const first = contents[0];
  if (first instanceof Tag) {
    if (first.tag !== 32769) {
      return new Tag(27, val);
    }
    contents[0] = first.contents;
  }
  return unwrapObj(contents);
});

// Tag 32769: Proxy (by name)
tagDecoders.set(32769, (val: unknown) => {
  const contents = tagContents(val);
  if (typeof contents === 'string' || typeof contents === 'number') {
    return decodeProxy(contents);
  }
  return new Tag(32769, val);
});

// Tag 258: Set
tagDecoders.set(258, (val: unknown) => {
  const contents = tagContents(val);
  if (contents instanceof Array) {
    return new Set(contents);
  }
  return new Tag(258, val);
});

// Tag 1: Date (epoch seconds)
tagDecoders.set(1, (val: unknown) => {
  const contents = tagContents(val);
  if (typeof contents === 'number') {
    return new Date(contents * 1000);
  }
  return new Tag(1, val);
});

// Tag 0: Date (ISO string) — decode only
tagDecoders.set(0, (val: unknown) => {
  const contents = tagContents(val);
  if (typeof contents === 'string') {
    return new Date(contents);
  }
  return new Tag(0, val);
});

// --- Encoding options ---

const encodeOptions = { types: typeEncoders };

// --- Decoding options ---

const decodeOptions = { tags: tagDecoders };

// --- Public API ---

/** Encode a value to CBOR bytes using the MoaT tag table. */
export function encodeMoat(value: unknown): Uint8Array {
  return encode(value, encodeOptions);
}

/** Decode CBOR bytes using the MoaT tag table. */
export function decodeMoat(data: Uint8Array | Buffer): unknown {
  return decode(data as Uint8Array, decodeOptions);
}

/** Encode a wire message (array) to CBOR bytes. */
export function encodeMessage(msg: unknown[]): Uint8Array {
  return encodeMoat(msg);
}

/** Decode a wire message from CBOR bytes. */
export function decodeMessage(data: Uint8Array | Buffer): unknown[] {
  return decodeMoat(data) as unknown[];
}

// Re-export commonly used items
export { Tag, Path, DProxy, Proxy, asProxy, name2obj, pushKw, popKw };
export { encodeError, unwrapObj, decodeProxy };

/** Check if a value is a plain object (not null, not array, not Map). */
function isPlainObject(v: unknown): v is Record<string, unknown> {
  return (
    v !== null &&
    typeof v === 'object' &&
    !(v instanceof Array) &&
    !(v instanceof Map) &&
    !(v instanceof Uint8Array) &&
    Object.getPrototypeOf(v) === Object.prototype
  );
}
