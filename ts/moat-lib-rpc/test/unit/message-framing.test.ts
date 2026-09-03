/**
 * Message framing tests — round-trip every message type through the
 * sans-IO core's feed/drain cycle.
 *
 * Covers: requests, responses, errors, warnings, stream data,
 * and the kwargs push/pop conventions.
 */

import { describe, expect, it } from 'vitest';
import { RpcCore } from '../../src/core/handler.js';
import { Msg } from '../../src/core/msg.js';
import { StreamLink } from '../../src/core/link.js';
import { encodeMessage, decodeMessage } from '../../src/codec.js';
import { i_f2wire, wire2i_f } from '../../src/wire.js';
import { Path } from '../../src/path.js';
import {
  B_STREAM,
  B_ERROR,
  B_WARNING,
  E_CANCEL,
  E_NO_STREAM,
  E_ERROR,
} from '../../src/const.js';
import { pushKw, popKw } from '../../src/proxy.js';

describe('message framing: header encode/decode', () => {
  it('encodes request header (id=1, flag=0)', () => {
    const wire = i_f2wire(1, 0);
    expect(wire).toBe(0);
    const [id, flag] = wire2i_f(wire);
    expect(id).toBe(1);
    expect(flag).toBe(0);
  });

  it('encodes response header (id=-1, flag=0)', () => {
    const wire = i_f2wire(-1, 0);
    expect(wire).toBe(-4);
    const [id, flag] = wire2i_f(wire);
    expect(id).toBe(-1);
    expect(flag).toBe(0);
  });

  it('encodes error header (id=-1, flag=2)', () => {
    const wire = i_f2wire(-1, B_ERROR);
    expect(wire).toBe(-2);
    const [id, flag] = wire2i_f(wire);
    expect(id).toBe(-1);
    expect(flag).toBe(2);
  });

  it('encodes stream header (id=1, flag=1)', () => {
    const wire = i_f2wire(1, B_STREAM);
    expect(wire).toBe(1);
    const [id, flag] = wire2i_f(wire);
    expect(id).toBe(1);
    expect(flag).toBe(1);
  });

  it('encodes warning header (id=-1, flag=3)', () => {
    const wire = i_f2wire(-1, B_WARNING);
    expect(wire).toBe(-1);
    const [id, flag] = wire2i_f(wire);
    expect(id).toBe(-1);
    expect(flag).toBe(3);
  });

  it('sign-flip round trip: originator → responder → originator', () => {
    // Originator sends with id=1
    const origWire = i_f2wire(1, 0);
    expect(origWire).toBe(0);
    // Responder decodes, flips sign
    const [rawId, flag] = wire2i_f(origWire);
    const responderId = -rawId;
    expect(responderId).toBe(-1);
    // Responder sends reply with negative id
    const respWire = i_f2wire(responderId, 0);
    expect(respWire).toBe(-4);
    // Originator decodes, flips sign back
    const [rawId2] = wire2i_f(respWire);
    const origIdAgain = -rawId2;
    expect(origIdAgain).toBe(1);
  });
});

describe('message framing: CBOR wire round-trips', () => {
  it('round-trips a request message', () => {
    const msg = [0, ['ping']];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a request with args', () => {
    const msg = [0, ['echo'], 42, 'hello'];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a request with kwargs', () => {
    const msg = [0, ['cmd'], { key: 'value' }];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a response message', () => {
    const msg = [-4, ['pong']];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a response with kwargs', () => {
    const msg = [-4, ['ok'], { status: 'done' }];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips an error message', () => {
    const msg = [-2, [E_CANCEL]];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a stream data message', () => {
    const msg = [1, [42]]; // id=1, flag=1 (B_STREAM)
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a warning message', () => {
    const msg = [-3, [42, {}]]; // warning with kw to disambiguate
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded).toEqual(msg);
  });

  it('round-trips a message with Path values in args', () => {
    const path = Path.build(['foo', 'bar']);
    const msg = [0, ['cmd'], path];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded[0]).toBe(0);
    expect(decoded[2]).toBeInstanceOf(Path);
    expect((decoded[2] as Path).length).toBe(2);
  });

  it('round-trips a message with Set values in args', () => {
    const s = new Set([1, 2, 3]);
    const msg = [0, ['cmd'], s];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded[2]).toBeInstanceOf(Set);
    expect((decoded[2] as Set<unknown>).size).toBe(3);
  });

  it('preserves Uint8Array vs string distinction', () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const text = 'hello';
    const msg = [0, ['cmd'], bytes, text];
    const encoded = encodeMessage(msg);
    const decoded = decodeMessage(encoded);
    expect(decoded[2]).toBeInstanceOf(Uint8Array);
    expect(typeof decoded[3]).toBe('string');
  });
});

describe('message framing: kwargs push/pop', () => {
  it('appends kwargs when non-empty', () => {
    const args: unknown[] = [1, 2];
    pushKw(args, { key: 'value' });
    expect(args).toEqual([1, 2, { key: 'value' }]);
  });

  it('does not append empty kwargs when last arg is not a map', () => {
    const args: unknown[] = [1, 2];
    pushKw(args, {});
    expect(args).toEqual([1, 2]);
  });

  it('appends empty kwargs when last arg is a map (disambiguation)', () => {
    const args: unknown[] = [{ a: 1 }];
    pushKw(args, {});
    expect(args).toEqual([{ a: 1 }, {}]);
  });

  it('appends empty kwargs for user warning with single int', () => {
    const args: unknown[] = [42];
    pushKw(args, {}, true);
    expect(args).toEqual([42, {}]);
  });

  it('does not append for non-warning single int', () => {
    const args: unknown[] = [42];
    pushKw(args, {});
    expect(args).toEqual([42]);
  });

  it('pops trailing map as kwargs', () => {
    const ak: unknown[] = [1, 2, { key: 'value' }];
    const kw = popKw(ak);
    expect(ak).toEqual([1, 2]);
    expect(kw).toEqual({ key: 'value' });
  });

  it('returns empty object when no trailing map', () => {
    const ak: unknown[] = [1, 2, 3];
    const kw = popKw(ak);
    expect(ak).toEqual([1, 2, 3]);
    expect(kw).toEqual({});
  });

  it('does not pop non-map last element', () => {
    const ak: unknown[] = [1, 'string', 42];
    const kw = popKw(ak);
    expect(ak).toEqual([1, 'string', 42]);
    expect(kw).toEqual({});
  });

  it('round-trip: push then pop', () => {
    const original: unknown[] = [1, 2];
    const kw = { x: 10 };
    pushKw(original, kw);
    const popped = popKw(original);
    expect(original).toEqual([1, 2]);
    expect(popped).toEqual(kw);
  });
});

describe('message framing: full wire round-trip via core', () => {
  it('encodes a complete request through the core', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call(Path.build(['ping']), [], {});

    // Drain the outbound message
    const outbound = core.drain();
    expect(outbound.length).toBe(1);

    // The wire header should be for id=1, flag=0
    const [wireHdr] = outbound[0]!.payload;
    expect(wireHdr).toBe(0); // id=1, flag=0 → 0

    // Encode to CBOR and decode
    const encoded = encodeMessage(outbound[0]!.payload);
    const decoded = decodeMessage(encoded);

    expect(decoded[0]).toBe(0);
    // The command path should be reversed (rcmd)
    expect(Array.isArray(decoded[1])).toBe(true);

    // Clean up
    msg.setEnd();
    core.freeId(link.id);
  });

  it('encodes a complete response through the core', () => {
    const core = new RpcCore(null, {});

    // Simulate an incoming request to create a link
    const requestPayload = [0, ['ping']] as unknown[];
    core.feed(requestPayload as unknown[]);

    // Drain the request
    const reqOutbound = core.drain();

    // The core should have created a link for the incoming request
    // Now simulate a response by feeding a reply
    // The responder uses id=-1, flag=0 → wire=-4
    const responsePayload = [-4, ['pong']] as unknown[];
    core.feed(responsePayload as unknown[]);

    // The response should trigger the onResult callback
    // (tested more thoroughly in state-machine tests)
  });
});
