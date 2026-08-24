/**
 * MsgSender + Caller — the client-side API.
 *
 * Mirrors MsgSender and Caller from moat/lib/rpc/base.py.
 *
 * Phase 1: Caller is a thenable (await sender.cmd("foo", 42)).
 * Phase 2 adds async-iterator / context-manager streaming.
 */

import { Msg, MsgResult } from '../core/msg.js';
import type { RpcCore } from '../core/handler.js';
import { Path } from '../path.js';
import type { PathElem } from '../path.js';

/** Unpack mode for Caller. */
export type ListMode = boolean | null | symbol;

const NOT_GIVEN: symbol = Symbol.for('NotGiven');

/**
 * Caller — the wrapper returned by MsgSender.cmd().
 *
 * Can be awaited (direct RPC call) for Phase 1.
 * Phase 2 adds async-context-manager streaming.
 */
export class Caller {
  private _core: RpcCore;
  private _cmd: Path | string;
  private _args: unknown[];
  private _kw: Record<string, unknown>;
  private _list: ListMode = NOT_GIVEN;

  constructor(core: RpcCore, cmd: Path | string, args: unknown[], kw: Record<string, unknown>) {
    this._core = core;
    this._cmd = cmd;
    this._args = args;
    this._kw = kw;
  }

  /** Make this object thenable. */
  then<TResult1 = MsgResult | unknown>(
    onfulfilled?: (value: MsgResult | unknown) => TResult1 | PromiseLike<TResult1>,
    onrejected?: (reason: unknown) => PromiseLike<TResult1>,
  ): Promise<TResult1> {
    return this._call().then(onfulfilled, onrejected);
  }

  private async _call(): Promise<MsgResult | unknown> {
    const { msg } = this._core.call(this._cmd, [...this._args], { ...this._kw });

    const result = await msg.waitReplied();

    if (this._list === NOT_GIVEN) {
      return result;
    }

    if (this._list === true) {
      // Always return a list
      if (Object.keys(result.kw).length > 0) {
        throw new Error('has dict');
      }
      return result.args;
    }

    if (this._list === false) {
      // Always return a dict
      if (result.args.length > 0) {
        throw new Error('has args');
      }
      return result.kw;
    }

    // null: best effort
    const kw = result.kw;
    if (Object.keys(kw).length > 0) {
      if (result.args.length > 0) {
        return result; // return the message object if both
      }
      return kw; // return dict if only kw
    }

    const args = result.args;
    if (args.length === 1) {
      return args[0]; // single arg directly
    }
    return args;
  }
}

/**
 * MsgSender — the client-side API of the MoaT command multiplexer.
 */
export class MsgSender {
  private _core: RpcCore;

  constructor(core: RpcCore) {
    this._core = core;
  }

  /** Issue a command. Returns a thenable Caller. */
  cmd(cmd: Path | string, ...args: unknown[]): Caller {
    return new Caller(this._core, cmd, args, {});
  }

  /** Issue a command with keyword arguments. */
  cmdKw(cmd: Path | string, kw: Record<string, unknown>, ...args: unknown[]): Caller {
    return new Caller(this._core, cmd, args, kw);
  }
}
