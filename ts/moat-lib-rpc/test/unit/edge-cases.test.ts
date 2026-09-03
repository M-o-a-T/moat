/**
 * Edge-case tests for the sans-IO core.
 *
 * Covers the tricky corners mentioned in the task acceptance criteria:
 * - Large IDs near 2^29 (bit-shift boundary)
 * - Empty payloads
 * - Error propagation through the full feed/drain cycle
 */

import { describe, expect, it } from 'vitest';
import { RpcCore } from '../../src/core/handler.js';
import { Msg } from '../../src/core/msg.js';
import { StreamLink } from '../../src/core/link.js';
import { encodeMessage, decodeMessage } from '../../src/codec.js';
import { i_f2wire, wire2i_f } from '../../src/wire.js';
import {
  B_STREAM,
  B_ERROR,
  B_WARNING,
  E_CANCEL,
  E_NO_STREAM,
  E_ERROR,
  E_NO_CMD,
  E_UNSPEC,
  E_SKIP,
} from '../../src/const.js';

describe('edge cases: large IDs near 2^29', () => {
  it('encodes and decodes id just below 2^29', () => {
    // 2^29 - 1 = 536870911. After subtracting 1: 536870910.
    // Shifted left by 2: 2147483640. Within signed-32 range.
    const id = 536870911;
    const w = i_f2wire(id, 0);
    const [decId, decFlag] = wire2i_f(w);
    expect(decId).toBe(id);
    expect(decFlag).toBe(0);
  });

  it('encodes and decodes id = 2^29', () => {
    // 2^29 = 536870912. After subtracting 1: 536870911.
    // Shifted left by 2: 2147483644. Still within signed-32 range (< 2^31).
    const id = 536870912;
    const w = i_f2wire(id, 0);
    expect(w).toBe(2147483644);
    const [decId, decFlag] = wire2i_f(w);
    expect(decId).toBe(id);
    expect(decFlag).toBe(0);
  });

  it('handles large negative IDs (responder replies)', () => {
    const id = -536870912;
    const w = i_f2wire(id, 0);
    const [decId, decFlag] = wire2i_f(w);
    expect(decId).toBe(id);
    expect(decFlag).toBe(0);
  });

  it('large IDs round-trip with all flag values', () => {
    const bigIds = [536870900, 536870911, 536870912];
    for (const id of bigIds) {
      for (let flag = 0; flag <= 3; flag++) {
        const w = i_f2wire(id, flag);
        const [di, df] = wire2i_f(w);
        expect(di).toBe(id);
        expect(df).toBe(flag);
      }
    }
  });

  it('feed/drain cycle works with moderately large IDs', () => {
    // Exhaust IDs up to a moderate number, then verify wire encoding
    const core = new RpcCore(null, {});
    for (let i = 0; i < 100; i++) {
      core.call(`cmd${i}`, [], {});
    }

    const { link } = core.call('test', ['arg'], {});
    expect(link.id).toBe(101);

    const outbound = core.drain();
    expect(outbound.length).toBeGreaterThan(0);
    const last = outbound[outbound.length - 1]!;
    expect(last.wire).toBe((101 - 1) * 4);
  });
});

describe('edge cases: empty payloads', () => {
  it('feeds a message with no args (just header + cmd)', () => {
    const core = new RpcCore(null, {
      onNewCommand: (_msg: Msg) => {},
    });

    const wireHeader = i_f2wire(1, 0);
    const msg = [wireHeader, ['ping']];
    const link = core.feed(msg);
    expect(link).not.toBeNull();
  });

  it('feeds a message with empty command path', () => {
    const core = new RpcCore(null, {
      onNewCommand: (_msg: Msg) => {},
    });

    const wireHeader = i_f2wire(1, 0);
    const msg = [wireHeader, []];
    const link = core.feed(msg);
    expect(link).not.toBeNull();
  });

  it('feeds a result with empty args', () => {
    const core = new RpcCore(null, {});

    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, 0);
    core.feed([replyWire]);

    // The reply should be processed (no crash)
    expect(core.isIdle).toBe(false);
  });

  it('handles empty CBOR-encoded message round-trip', () => {
    const encoded = encodeMessage([]);
    expect(encoded.length).toBe(1);
    expect(encoded[0]).toBe(0x80);
  });

  it('handles nil/null payload in message', () => {
    const core = new RpcCore(null, {
      onNewCommand: (_msg: Msg) => {},
    });

    const wireHeader = i_f2wire(1, 0);
    expect(() => core.feed([wireHeader, null])).not.toThrow();
  });
});

describe('edge cases: error propagation', () => {
  it('propagates E_CANCEL error through feed', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', ['arg'], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_CANCEL]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('propagates E_NO_STREAM error through feed', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_NO_STREAM]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('propagates E_ERROR (generic remote error) through feed', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_ERROR]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('propagates E_UNSPEC (stop) through feed', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_UNSPEC]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('propagates E_SKIP (skipped data) through feed', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_SKIP]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('propagates E_NO_CMD (unknown command) through feed', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_NO_CMD]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('propagates NoCmd with depth (E_NO_CMD - n)', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_NO_CMD - 2]]);

    expect(msg.hasResult).toBe(true);
    expect(msg.isError).toBe(true);
  });

  it('error result rejects waitReplied()', async () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_ERROR);
    core.feed([replyWire, [E_CANCEL]]);

    await expect(msg.waitReplied()).rejects.toThrow();
  });

  it('warning (B_WARNING) does not terminate the stream', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    const replyWire = i_f2wire(-id, B_WARNING);
    core.feed([replyWire, ['some warning']]);

    expect(msg.hasResult).toBe(false);
    expect(msg.warnings.length).toBe(1);
  });

  it('flow control warning (B_WARNING + single int) is internal', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    // Feed a flow-control warning: [replyWire, 42]
    // The core detects flag===B_WARNING && single numeric arg → B_WARNING_INTERNAL
    const replyWire = i_f2wire(-id, B_WARNING);
    core.feed([replyWire, 42]);

    expect(msg.hasResult).toBe(false);
    // Flow control is internal — no warning added
    expect(msg.warnings.length).toBe(0);
  });

  it('multiple sequential errors on different IDs', () => {
    const core = new RpcCore(null, {});

    const calls = [];
    for (let i = 0; i < 3; i++) {
      calls.push(core.call(`cmd${i}`, [], {}));
    }

    for (let i = 0; i < 3; i++) {
      const id = calls[i]!.link.id;
      const replyWire = i_f2wire(-id, B_ERROR);
      core.feed([replyWire, [E_CANCEL]]);
    }

    for (const { msg } of calls) {
      expect(msg.hasResult).toBe(true);
      expect(msg.isError).toBe(true);
    }
  });

  it('drops spurious replies for unknown positive IDs', () => {
    const core = new RpcCore(null, {});

    // A reply to id=1 (which we never initiated): wire=i_f2wire(-1,0)
    // After sign flip: i=1, which is positive → spurious
    const wireHeader = i_f2wire(-1, 0);
    const result = core.feed([wireHeader, ['result']]);
    expect(result).toBeNull();
  });

  it('drops spurious error replies for unknown IDs', () => {
    const core = new RpcCore(null, {});

    // An error reply to id=1 (never initiated): wire=i_f2wire(-1, B_ERROR)
    const wireHeader = i_f2wire(-1, B_ERROR);
    const result = core.feed([wireHeader, [E_CANCEL]]);
    expect(result).toBeNull();
  });
});
