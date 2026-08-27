import { describe, expect, it } from 'vitest';
import { decodeStreamError, StopMe, NoStream, NoCmds, NoCmd, RemoteError, CancelledError, SkippedData, MustStream, Flow } from '../../src/errors.js';
import { E_UNSPEC, E_NO_STREAM, E_CANCEL, E_NO_CMDS, E_SKIP, E_ERROR, E_NO_CMD, E_MUST_STREAM } from '../../src/const.js';

describe('error taxonomy', () => {
  it('decodes E_UNSPEC to StopMe', () => {
    const err = decodeStreamError([E_UNSPEC]);
    expect(err).toBeInstanceOf(StopMe);
  });

  it('decodes E_NO_STREAM to NoStream', () => {
    const err = decodeStreamError([E_NO_STREAM]);
    expect(err).toBeInstanceOf(NoStream);
  });

  it('decodes E_CANCEL to CancelledError', () => {
    const err = decodeStreamError([E_CANCEL]);
    expect(err).toBeInstanceOf(CancelledError);
  });

  it('decodes E_NO_CMDS to NoCmds', () => {
    const err = decodeStreamError([E_NO_CMDS]);
    expect(err).toBeInstanceOf(NoCmds);
  });

  it('decodes E_SKIP to SkippedData', () => {
    const err = decodeStreamError([E_SKIP]);
    expect(err).toBeInstanceOf(SkippedData);
  });

  it('decodes E_MUST_STREAM to MustStream', () => {
    const err = decodeStreamError([E_MUST_STREAM]);
    expect(err).toBeInstanceOf(MustStream);
  });

  it('decodes E_ERROR to RemoteError', () => {
    const err = decodeStreamError([E_ERROR]);
    expect(err).toBeInstanceOf(RemoteError);
  });

  it('decodes E_NO_CMD to NoCmd with depth', () => {
    const err = decodeStreamError([E_NO_CMD - 2]);
    expect(err).toBeInstanceOf(NoCmd);
    expect((err as NoCmd).depth).toBe(2);
  });

  it('decodes non-negative int to Flow', () => {
    const err = decodeStreamError([42]);
    expect(err).toBeInstanceOf(Flow);
    expect((err as Flow).n).toBe(42);
  });

  it('passes through Error instances', () => {
    const original = new Error('test');
    const err = decodeStreamError([original]);
    expect(err).toBe(original);
  });

  it('decodes multi-element payload to StreamError', () => {
    const err = decodeStreamError(['some', 'data']);
    expect(err).toBeInstanceOf(Error);
  });
});
