/**
 * MsgHandler — command dispatch base class.
 *
 * Mirrors MsgHandler.handle() from moat/lib/rpc/base.py.
 *
 * Implements path-based command dispatch:
 *   empty path → cmd()/stream() or ShortCommandError
 *   doc_ → documentation
 *   cmd_X / stream_X → leaf handlers
 *   rdy_ → readiness check
 *   sub_X → recursive dispatch
 *   else → KeyError (marshalled as _rErr)
 */

import { Msg } from '../core/msg.js';
import { Path } from '../path.js';
import type { PathElem } from '../path.js';
import { ShortCommandError, NotReadyError } from '../errors.js';
import type { CommandDispatcher } from '../core/handler.js';

/** Type for a command handler function. */
export type CmdFn = (msg: Msg, ...args: unknown[]) => Promise<unknown> | unknown;
export type StreamFn = (msg: Msg) => Promise<void>;

/**
 * MsgHandler — message dispatch using a Path-based prefix.
 *
 * Implement `cmd_NAME` and/or `stream_NAME` methods for simple/streamed calls.
 * Implement `sub_NAME` properties (or methods returning MsgHandlers) for sub-routing.
 */
export abstract class MsgHandler implements CommandDispatcher {
  /** Skip readiness checks for subcommands. */
  static SKIP_RDY = false;

  /** The configuration name (for error messages). */
  get cfg_name(): string {
    return this.constructor.name;
  }

  async handle(msg: Msg, rcmd: PathElem[]): Promise<void> {
    // Process direct calls (empty path)
    if (rcmd.length === 0) {
      if (!msg.canStream) {
        const cmd = (this as unknown as { cmd?: CmdFn }).cmd;
        if (cmd !== undefined) {
          return await this._callSimple(msg, cmd);
        }
      }
      const stream = (this as unknown as { stream?: StreamFn }).stream;
      if (stream !== undefined) {
        return await this._callStream(msg, stream);
      }
      throw new ShortCommandError();
    }

    // Process documentation requests
    if (rcmd.length <= 2 && rcmd[0] === 'doc_') {
      if (msg.args.length > 0 || Object.keys(msg.kw).length > 0) {
        throw new TypeError('doc takes no args');
      }
      const docKey = rcmd.length > 1 ? `doc_${String(rcmd[1])}` : 'doc';
      const doc = (this as unknown as Record<string, unknown>)[docKey];
      if (doc !== undefined) {
        await msg.result(doc);
        return;
      }
    }

    // Process command handlers of this class
    if (rcmd.length === 1) {
      const cmdName = `cmd_${String(rcmd[0])}`;
      if (!msg.canStream) {
        const cmd = (this as unknown as Record<string, CmdFn | undefined>)[cmdName];
        if (cmd !== undefined) {
          return await this._callSimple(msg, cmd);
        }
      }
      const streamName = `stream_${String(rcmd[0])}`;
      const streamFn = (this as unknown as Record<string, StreamFn | undefined>)[streamName];
      if (streamFn !== undefined) {
        return await this._callStream(msg, streamFn);
      }
    }

    // Readiness check
    let isRdy = false;
    if (rcmd[0] === 'rdy_') {
      // Phase 1: trivial "answer None" fallback
      isRdy = true;
    }

    // Find a subcommand
    const scmd = rcmd.pop()!;
    const sub = this.findSub(scmd);
    if (sub !== null && sub !== undefined) {
      const handleFn = (sub as unknown as { handle?: (msg: Msg, rcmd: PathElem[]) => Promise<void> }).handle;
      if (handleFn) {
        return await handleFn.call(sub, msg, rcmd);
      }
      // It's a callable
      if (typeof sub === 'function') {
        return await (sub as (msg: Msg, rcmd: PathElem[]) => Promise<void>)(msg, rcmd);
      }
    }

    if (isRdy) {
      await msg.result(undefined);
      return;
    }

    // Unknown command → KeyError (marshalled as _rErr by the codec)
    throw new KeyError(String(scmd), this.cfg_name);
  }

  /** Resolve a subcommand. Override for custom routing. */
  findSub(scmd: PathElem): MsgHandler | ((msg: Msg, rcmd: PathElem[]) => Promise<void>) | null {
    if (typeof scmd !== 'string') return null;
    const name = `sub_${scmd}`;
    const sub = (this as unknown as Record<string, unknown>)[name];
    if (sub === undefined) return null;
    return sub as MsgHandler;
  }

  /** Handle a non-streamed call endpoint. */
  private async _callSimple(msg: Msg, cmd: CmdFn): Promise<void> {
    try {
      const res = await cmd.call(this, msg, ...msg.args);
      if (res instanceof Msg) {
        await msg.result(...res.args);
      } else if (res !== undefined) {
        await msg.result(res);
      } else {
        await msg.result(undefined);
      }
    } catch (exc) {
      if (msg.remote === null) throw exc;
      await msg.mlSendError(exc instanceof Error ? exc : new Error(String(exc)));
    }
  }

  /** Handle a streamed call endpoint (phase 2 stub). */
  private async _callStream(msg: Msg, cmd: StreamFn): Promise<void> {
    try {
      await cmd.call(this, msg);
    } catch (exc) {
      if (msg.remote === null) throw exc;
      await msg.mlSendError(exc instanceof Error ? exc : new Error(String(exc)));
    }
    if (msg._streamOut !== 3 /* S_END */) {
      await msg.result();
    }
  }
}

/** Simple KeyError class (marshalled as _rErr on the wire). */
class KeyError extends Error {
  constructor(public key: string, public source: string) {
    super(`KeyError: ${key} in ${source}`);
    this.name = 'KeyError';
  }
}
