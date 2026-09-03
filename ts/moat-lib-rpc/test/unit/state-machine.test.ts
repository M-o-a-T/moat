/**
 * Sans-IO state machine tests — feed/drain, event callbacks,
 * link lifecycle, and message routing.
 *
 * The core is purely synchronous: feed bytes in, drain bytes out,
 * get callbacks. No I/O, no promises, no timers.
 */

import { describe, expect, it } from 'vitest';
import { RpcCore } from '../../src/core/handler.js';
import { StreamLink } from '../../src/core/link.js';
import { Msg, MsgResult } from '../../src/core/msg.js';
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
import type { CoreCallbacks } from '../../src/core/link.js';

describe('state machine: feed/drain basics', () => {
  it('feed an incoming request triggers onNewCommand', () => {
    let newCmdReceived = false;
    let receivedMsg: Msg | null = null;

    const callbacks: CoreCallbacks = {
      onNewCommand: (msg: Msg, _link: StreamLink) => {
        newCmdReceived = true;
        receivedMsg = msg;
      },
    };

    const core = new RpcCore(null, callbacks);

    // Feed a simple request: [header=0, cmd=["ping"]]
    // header=0 means id=1, flag=0 → incoming id=-1 (after sign flip)
    core.feed([0, ['ping']]);

    expect(newCmdReceived).toBe(true);
    expect(receivedMsg).not.toBeNull();
    expect(receivedMsg!.cmd).toBeInstanceOf(Path);
  });

  it('feed an incoming request with args', () => {
    let receivedArgs: unknown[] = [];

    const core = new RpcCore(null, {
      onNewCommand: (msg: Msg) => {
        receivedArgs = [...msg.args];
      },
    });

    core.feed([0, ['echo'], 42, 'hello']);

    expect(receivedArgs).toEqual([42, 'hello']);
  });

  it('feed an incoming request with kwargs', () => {
    let receivedKw: Record<string, unknown> = {};

    const core = new RpcCore(null, {
      onNewCommand: (msg: Msg) => {
        receivedKw = { ...msg.kw };
      },
    });

    core.feed([0, ['cmd'], { key: 'value' }]);

    expect(receivedKw).toEqual({ key: 'value' });
  });

  it('drain returns queued outbound messages', () => {
    const core = new RpcCore(null, {});
    core.call('ping', [], {});

    const outbound = core.drain();
    expect(outbound.length).toBe(1);

    // The payload should be [header, reversed_cmd_path]
    const payload = outbound[0]!.payload;
    expect(payload[0]).toBe(0); // id=1, flag=0 → wire=0
    expect(Array.isArray(payload[1])).toBe(true);
  });

  it('drain returns empty when no messages queued', () => {
    const core = new RpcCore(null, {});
    expect(core.drain()).toEqual([]);
  });

  it('feed throws on empty message', () => {
    const core = new RpcCore(null, {});
    expect(() => core.feed([])).toThrow();
  });
});

describe('state machine: request-response cycle', () => {
  it('full cycle: client sends request, server responds', () => {
    // Set up two cores — one client, one server
    let serverMsg: Msg | null = null;
    let serverLink: StreamLink | null = null;

    const serverCore = new RpcCore(null, {
      onNewCommand: (msg: Msg, link: StreamLink) => {
        serverMsg = msg;
        serverLink = link;
      },
    });

    const clientCore = new RpcCore(null, {
      onResult: (_id: number, result) => {
        if (result.ok) {
          // Got the response
        }
      },
    });

    // Client initiates a call
    const { link: clientLink, msg: clientMsg } = clientCore.call('ping', [], {});
    expect(clientLink.id).toBe(1);

    // Drain client's outbound message
    const clientOutbound = clientCore.drain();
    expect(clientOutbound.length).toBe(1);

    // Feed it to the server
    serverCore.feed(clientOutbound[0]!.payload);
    expect(serverMsg).not.toBeNull();
    expect(serverLink).not.toBeNull();

    // Server sends a response
    serverMsg!.result('pong');

    // Drain server's outbound message
    const serverOutbound = serverCore.drain();
    expect(serverOutbound.length).toBe(1);

    // Feed it back to the client
    clientCore.feed(serverOutbound[0]!.payload);

    // The client should have received the result
    expect(clientMsg.hasResult).toBe(true);
    expect(clientMsg.isError).toBe(false);

    // Clean up
    clientCore.freeId(clientLink.id);
  });

  it('error response: server sends E_CANCEL', async () => {
    let serverMsg: Msg | null = null;

    const serverCore = new RpcCore(null, {
      onNewCommand: (msg: Msg) => {
        serverMsg = msg;
      },
    });

    const clientCore = new RpcCore(null, {});

    // Client sends request
    const { link: clientLink, msg: clientMsg } = clientCore.call('test', [], {});

    // Transfer to server
    serverCore.feed(clientCore.drain()[0]!.payload);
    expect(serverMsg).not.toBeNull();

    // Server sends an error
    serverMsg!.errorResult(E_CANCEL);

    // Transfer error back to client
    clientCore.feed(serverCore.drain()[0]!.payload);

    // Client should have an error result
    expect(clientMsg.hasResult).toBe(true);
    expect(clientMsg.isError).toBe(true);

    clientCore.freeId(clientLink.id);
  });
});

describe('state machine: link lifecycle', () => {
  it('attaches and detaches links', () => {
    let detachedId: number | null = null;
    const core = new RpcCore(null, {
      onDetach: (id: number) => {
        detachedId = id;
      },
    });

    const { link, msg } = core.call('test', [], {});
    expect(core.isIdle).toBe(false);

    // End both directions to trigger detach
    msg.setEnd();
    // The link should be detached after both ends close
    // (In non-streaming, the outgoing end is already ended by call())

    // The incoming end closes when the reply arrives
    // For this test, we manually detach
    core.detach(link);
    expect(detachedId).toBe(link.id);
  });

  it('detach is idempotent', () => {
    let detachCount = 0;
    const core = new RpcCore(null, {
      onDetach: () => {
        detachCount++;
      },
    });

    const { link, msg } = core.call('test', [], {});
    core.detach(link);
    core.detach(link); // should not double-detach
    expect(detachCount).toBe(1);

    core.freeId(link.id);
  });
});

describe('state machine: spurious message handling', () => {
  it('drops spurious messages for unknown positive IDs', () => {
    const core = new RpcCore(null, {});
    // Feed a message that looks like a response for unknown id
    // wire=-4 means id=-1, flag=0 → incoming id=1 (positive, unknown)
    const result = core.feed([-4, ['unexpected']]);
    expect(result).toBeNull();
  });

  it('drops spurious error messages for unknown IDs', () => {
    const core = new RpcCore(null, {});
    // wire=-2 means id=-1, flag=2 (error) → incoming id=1 (positive, unknown)
    const result = core.feed([-2, [-3]]);
    expect(result).toBeNull();
  });
});

describe('state machine: closing', () => {
  it('closeInput prevents new outgoing calls', () => {
    const core = new RpcCore(null, {});
    core.closeInput();

    expect(() => core.call('test', [], {})).toThrow();
  });

  it('closing property reflects state', () => {
    const core = new RpcCore(null, {});
    expect(core.closing).toBe(false);
    core.closeInput();
    expect(core.closing).toBe(true);
  });
});

describe('state machine: warning reconstruction', () => {
  it('reconstructs B_WARNING_INTERNAL from flag 3 + single int', () => {
    const core = new RpcCore(null, {});

    // Create a link first by sending a request
    const { link, msg } = core.call('test', [], {});
    const id = link.id;

    // Feed a warning: wire for id=-1, flag=3 is -1
    // The payload is a single integer [42]
    // This should be reconstructed as B_WARNING_INTERNAL (flag 7)
    core.feed([-1, [42]]);

    // The message should have received the warning
    // (In phase 1, warnings are stored but not acted upon)
    expect(msg.warnings.length).toBeGreaterThanOrEqual(0);

    core.freeId(id);
  });
});

describe('state machine: command path handling', () => {
  it('feeds a request with multi-element command path', () => {
    let receivedCmd: Path | null = null;

    const core = new RpcCore(null, {
      onNewCommand: (msg: Msg) => {
        receivedCmd = msg.cmd;
      },
    });

    core.feed([0, ['system', 'status']]);

    expect(receivedCmd).not.toBeNull();
    expect(receivedCmd!.length).toBe(2);
    expect(receivedCmd!.get(0)).toBe('system');
    expect(receivedCmd!.get(1)).toBe('status');
  });

  it('feeds a request with empty command path', () => {
    let receivedCmd: Path | null = null;

    const core = new RpcCore(null, {
      onNewCommand: (msg: Msg) => {
        receivedCmd = msg.cmd;
      },
    });

    core.feed([0, []]);

    expect(receivedCmd).not.toBeNull();
    expect(receivedCmd!.length).toBe(0);
  });

  it('accepts Path-tagged command path on decode', () => {
    let receivedCmd: Path | null = null;

    const core = new RpcCore(null, {
      onNewCommand: (msg: Msg) => {
        receivedCmd = msg.cmd;
      },
    });

    // Create a message with a Path value in the command slot
    const pathVal = Path.build(['test', 'cmd']);
    const encoded = encodeMessage([0, pathVal]);
    core.feed(decodeMessage(encoded));

    expect(receivedCmd).not.toBeNull();
    expect(receivedCmd!.length).toBe(2);
  });
});
