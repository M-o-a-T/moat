/**
 * ID pool tests — tiered allocation, recycling, and reuse delay.
 *
 * Mirrors the tiered free-ID pools from HandlerStream.__init__
 * and the reuse-delay timer from the async adapter.
 */

import { describe, expect, it } from 'vitest';
import { RpcCore } from '../../src/core/handler.js';
import { StreamLink } from '../../src/core/link.js';
import { Msg } from '../../src/core/msg.js';

describe('ID pool: tiered allocation', () => {
  it('allocates sequential IDs starting from 1', () => {
    const core = new RpcCore(null, {});
    const ids: number[] = [];
    for (let i = 0; i < 5; i++) {
      const { link } = core.call(`cmd${i}`, [], {});
      ids.push(link.id);
    }
    expect(ids).toEqual([1, 2, 3, 4, 5]);

    // Clean up
    for (const id of ids) {
      core.freeId(id);
    }
  });

  it('recycles freed IDs from the smallest tier first', () => {
    const core = new RpcCore(null, {});

    // Allocate 3 IDs
    const { link: l1, msg: m1 } = core.call('a', [], {});
    const { link: l2, msg: m2 } = core.call('b', [], {});
    const { link: l3, msg: m3 } = core.call('c', [], {});
    expect(l1.id).toBe(1);
    expect(l2.id).toBe(2);
    expect(l3.id).toBe(3);

    // Free id=2: detach the link first, then free the ID
    m2.setEnd();
    core.detach(l2);
    core.freeId(2);

    // Next allocation should reuse id=2 (from _id1)
    const { link: l4 } = core.call('d', [], {});
    expect(l4.id).toBe(2);

    // Clean up
    m1.setEnd(); core.detach(l1); core.freeId(1);
    m3.setEnd(); core.detach(l3); core.freeId(3);
    core.detach(l4); core.freeId(4);
  });

  it('recycles IDs in tier order: <6 first, then <64, then rest', () => {
    const core = new RpcCore(null, {});

    // Allocate enough IDs to populate all tiers
    const links: { link: StreamLink; msg: Msg }[] = [];
    for (let i = 0; i < 70; i++) {
      links.push(core.call(`c${i}`, [], {}));
    }

    // Free some from each tier (detach first)
    // id=3 is at index 2
    links[2].msg.setEnd();
    core.detach(links[2].link);
    core.freeId(3);   // <6 tier

    // id=50 is at index 49
    links[49].msg.setEnd();
    core.detach(links[49].link);
    core.freeId(50);  // <64 tier

    // id=65 is at index 64
    links[64].msg.setEnd();
    core.detach(links[64].link);
    core.freeId(65); // rest tier

    // Next allocations should come from <6 first
    const { link: a1 } = core.call('x', [], {});
    expect(a1.id).toBe(3); // from _id1

    const { link: a2 } = core.call('y', [], {});
    expect(a2.id).toBe(50); // from _id2

    const { link: a3 } = core.call('z', [], {});
    expect(a3.id).toBe(65); // from _id3

    // Clean up all remaining links
    for (const { link, msg } of links) {
      if (link.id !== 3 && link.id !== 50 && link.id !== 65) {
        msg.setEnd();
        core.detach(link);
        core.freeId(link.id);
      }
    }
    core.detach(a1); core.freeId(3);
    core.detach(a2); core.freeId(50);
    core.detach(a3); core.freeId(65);
  });

  it('never recycles negative (responder) IDs', () => {
    const core = new RpcCore(null, {});

    // freeId with negative or zero should be a no-op
    core.freeId(-1);
    core.freeId(-5);
    core.freeId(0);

    // Next allocation should still be from counter (id=1)
    const { link } = core.call('test', [], {});
    expect(link.id).toBe(1);

    core.freeId(1);
  });

  it('freeId assigns to correct tier on recycle', () => {
    const core = new RpcCore(null, {});

    // Allocate and free IDs in different tier ranges
    core.freeId(5);   // <6 → _id1
    core.freeId(10);  // <64 → _id2
    core.freeId(100); // rest → _id3

    // _id1 should be served first
    const { link: l1 } = core.call('a', [], {});
    expect(l1.id).toBe(5);

    // Then _id2
    const { link: l2 } = core.call('b', [], {});
    expect(l2.id).toBe(10);

    // Then _id3
    const { link: l3 } = core.call('c', [], {});
    expect(l3.id).toBe(100);

    core.freeId(5);
    core.freeId(10);
    core.freeId(100);
  });
});

describe('ID pool: isIdle tracking', () => {
  it('is idle when no messages and no pending frees', () => {
    const core = new RpcCore(null, {});
    expect(core.isIdle).toBe(true);
  });

  it('is not idle when messages are in flight', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    // The call() queues an outbound message, so isIdle is false
    expect(core.isIdle).toBe(false);

    // Clean up
    core.drain();
    msg.setEnd();
    core.detach(link);
    core.freeId(link.id);
  });

  it('is not idle when IDs are pending free', () => {
    const core = new RpcCore(null, {});
    const { link, msg } = core.call('test', [], {});
    // Drain the outbound message queued by call()
    core.drain();
    msg.setEnd();
    core.markPendingFree(link.id);
    expect(core.isIdle).toBe(false);

    // After detaching and freeing, should be idle
    core.detach(link);
    core.freeId(link.id);
    expect(core.isIdle).toBe(true);
  });
});

describe('ID pool: detach triggers onDetach callback', () => {
  it('calls onDetach when a link is detached', () => {
    let detachedId: number | null = null;
    const core = new RpcCore(null, {
      onDetach: (id: number) => {
        detachedId = id;
      },
    });

    // Feed an incoming request to create a link
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    // Detach the link
    core.detach(link);
    expect(detachedId).toBe(id);

    core.freeId(id);
  });

  it('does not call onDetach for negative (responder) IDs', () => {
    let detachedCalled = false;
    const core = new RpcCore(null, {
      onDetach: () => {
        detachedCalled = true;
      },
    });

    // Create a link with a negative ID (simulating responder side)
    const link = new StreamLink(core, -1);
    core.attach(link);

    // Detach — should not trigger onDetach (negative IDs not recycled)
    core.detach(link);
    expect(detachedCalled).toBe(false);
  });
});

describe('ID pool: large ID handling (no 32-bit overflow)', () => {
  it('handles IDs near 2^29 without overflow', () => {
    const core = new RpcCore(null, {});

    // Free a large ID directly
    const bigId = 0x20000000; // 2^29
    core.freeId(bigId);

    // Should be recyclable from _id3
    const { link } = core.call('big', [], {});
    expect(link.id).toBe(bigId);

    core.freeId(bigId);
  });
});
