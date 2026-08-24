/**
 * Proxy / error marshalling for the MoaT CBOR codec.
 *
 * Mirrors moat/lib/proxy/_impl.py and moat/lib/codec/_moat_cbor.py.
 *
 * Tag 27: DProxy / wrapped object / error → [name, *args, ?kw]
 * Tag 32769: Proxy (by name) → string/int name
 */

import { RemoteError } from './errors.js';

/** Registry mapping proxy names ↔ constructors. */
const nameToCtor = new Map<string, new (...args: unknown[]) => unknown>();
const ctorToName = new Map<Function, string>();

/** Register a class under a proxy name. */
export function asProxy(name: string, cls: any): void {
  nameToCtor.set(name, cls as unknown as new (...args: unknown[]) => unknown);
  ctorToName.set(cls, name);
}

/** Look up a constructor by proxy name. */
export function name2obj(name: string): (new (...args: unknown[]) => unknown) | undefined {
  return nameToCtor.get(name);
}

/** Look up a proxy name for a constructor. */
export function obj2name(cls: Function): string | undefined {
  return ctorToName.get(cls);
}

/** A DProxy — opaque proxy object with data. */
export class DProxy {
  constructor(
    public name: string,
    public a: unknown[],
    public k: Record<string, unknown>,
  ) {}
}

/** A Proxy — reference by name. */
export class Proxy {
  constructor(public name: string | number) {}
}

// --- Pre-register standard error proxy names ---

asProxy('_rErr', RemoteError);
asProxy('_CSMErr', class StopMeProxy extends RemoteError {});
asProxy('_CSDErr', class SkippedDataProxy extends RemoteError {});
asProxy('_CNsErr', class NoStreamProxy extends RemoteError {});
asProxy('_CNCsErr', class NoCmdsProxy extends RemoteError {});
asProxy('_CNCErr', class NoCmdProxy extends RemoteError {});
asProxy('_CWSErr', class WantsStreamProxy extends RemoteError {});
asProxy('_CMSErr', class MustStreamProxy extends RemoteError {});
asProxy('_NRdyErr', class NotReadyErrorProxy extends Error {});
asProxy('_SCmdErr', class ShortCommandErrorProxy extends Error {});
asProxy('_LCmdErr', class LongCommandErrorProxy extends Error {});

// Root path proxies

asProxy('_p', Proxy);

/**
 * Wrap an error for transmission.
 *
 * Encode: prefer a registered proxy name under tag 32769;
 * else emit tag 27 ["_rErr", errorClassName, ...args].
 *
 * @returns [tag, value] pair for cbor2, or null if not encodable.
 */
export function encodeError(error: Error): [number, unknown] | null {
  // Check if the error's constructor is registered
  const name = obj2name(error.constructor);
  if (name) {
    return [32769, name];
  }

  // Check if the error's prototype chain has a registered name
  let proto = Object.getPrototypeOf(error);
  while (proto && proto !== Object.prototype) {
    const ctor = proto.constructor;
    const n = ctorToName.get(ctor);
    if (n) {
      return [32769, n];
    }
    proto = Object.getPrototypeOf(proto);
  }

  // Fall back to _rErr with the class name and args
  const res: unknown[] = ['_rErr', error.constructor.name];
  // Try to get error args
  if ('args' in error && Array.isArray((error as unknown as { args: unknown[] }).args)) {
    res.push(...(error as unknown as { args: unknown[] }).args);
  } else if (error.message) {
    res.push(error.message);
  }
  return [27, res];
}

/**
 * Unwrap / deserialize an object from a tag-27 DProxy payload.
 *
 * @param val - The array [name, *args, ?kw]
 * @returns The reconstructed object, or a DProxy if the name is unknown.
 */
export function unwrapObj(val: unknown[]): unknown {
  const [pk, ...a] = val;
  if (typeof pk !== 'string') {
    // Already decoded (was tagged and de-proxied)
    return new DProxy(String(pk), a, {});
  }

  const ctor = nameToCtor.get(pk);
  if (!ctor) {
    // Unknown proxy — return as DProxy
    const kw = popKw(a);
    return new DProxy(pk, a, kw);
  }

  const kw = popKw(a);
  try {
    const obj = new ctor(...a);
    for (const [k, v] of Object.entries(kw)) {
      Object.defineProperty(obj, k, { value: v, enumerable: true, writable: true });
    }
    return obj;
  } catch {
    // Constructor failed — return as DProxy
    return new DProxy(pk, a, kw);
  }
}

/**
 * Deserialize a tag-32769 Proxy (by name).
 * @param val - The name (string or int).
 */
export function decodeProxy(val: string | number): unknown {
  const obj = nameToCtor.get(String(val));
  if (obj) return obj;
  return new Proxy(val);
}

// --- push_kw / pop_kw (mirrors moat/util/pp.py) ---

/**
 * Add kwargs to the args list, if required.
 *
 * The mapping is appended if:
 * - it is not empty.
 * - the last argument is a mapping (Map/object).
 * - the argument of a user-level warning consists of a single integer.
 */
export function pushKw(
  args: unknown[],
  kwargs: Record<string, unknown> | Map<string, unknown> | null,
  isWarn = false,
): void {
  const kwObj =
    kwargs instanceof Map ? Object.fromEntries(kwargs) : (kwargs ?? {});
  const hasKw = Object.keys(kwObj).length > 0;
  const lastIsMap =
    args.length > 0 && (args[args.length - 1] instanceof Map || isPlainObject(args[args.length - 1]));
  const isWarnInt = isWarn && args.length === 1 && typeof args[0] === 'number';

  if (hasKw || lastIsMap || isWarnInt) {
    args.push(kwObj);
  }
}

/**
 * Unpack an args-and-maybe-trailing-kwargs list.
 *
 * Removes and returns the trailing mapping if present; otherwise {}.
 */
export function popKw(ak: unknown[]): Record<string, unknown> {
  if (ak.length > 0) {
    const last = ak[ak.length - 1];
    if (last instanceof Map) {
      ak.pop();
      return Object.fromEntries(last as Map<string, unknown>);
    }
    if (isPlainObject(last)) {
      ak.pop();
      return last as Record<string, unknown>;
    }
  }
  return {};
}

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
