# command line interface
from __future__ import annotations

import anyio
import sys
import time

import asyncclick as click
from attrs import define, field

from moat.util import NotGiven, get_p
from moat.lib.path import P, Path
from moat.link.client import Link
from moat.link.schema import schema_path, validate_instance

from typing import Any


@click.group(short_help="Manage data flows.")
@click.pass_context
async def cli(ctx):
    """
    This subcommand reads data flow controls stored in the MoaT-Link service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg, common=True))


async def _flow_error(conn, path: Path, data: Any) -> Exception | None:
    """Return the schema validation error for one message, if any."""
    try:
        schema = await conn.d_search(schema_path(path))
    except KeyError:
        return None
    try:
        validate_instance(schema, data)
    except Exception as exc:
        return exc
    return None


async def _flow_record_error(conn, path: Path, data: Any, exc: Exception) -> None:
    """Write one error record."""
    await conn.e_info(
        P("flow") + path,
        msg,
        data_path=path,
        data=data,
        detail=str(exc) if exc else None,
    )


def _gen_paths(data:Mapping, p:Path=Path()) -> Iterator[tuple[Path,dict[str,Any]]]:
    if not isinstance(data,Mapping):
        return
    if "_" in data:
        yield p,data["_"]
        return
    for k,v in data:
        yield from _gen_paths(v, p/k)

def _check_limits(data,chk:dict) -> str|None:
    # XXX check against min/max
    return None

@define
class PathTimer:
    p:Path=field(eq=True,hash=True)
    v:Any=field(eq=False,hash=False)
    chk:dict=field(eq=False,hash=False)

class FlowMon:
    def __init__(self, conn:Link, path:Path):
        self.conn = conn
        self.path = path

        self.dest = TimerMap()  # verify destinations
        self.delay = TimerMap()
        self.values = attrdict()  # past values

    def check_data(self, p:Path, v:Any, chk:dict, m:MsgMeta) -> str|None:
        """
        - check min/max/step
        - queue a dest value check, if required
        - queue a timeout for updates
        """
        old_val = self.value.get(p,NotGiven)
        # TODO check min/max
        if (step := chk.get("maxstep",-1)) > 0:
            if (s := abs(old_val-v)) > step:
                return f"Step {s} > {step}"

        self.value.set_(p,v)
        if "timeout" not in chk and "copied" not in chk:
            return None

        tm=PathTimer(p,v,chk)
        if (cop := chk.get("copied", None)) is not None:
            self.dest[tm]=cop.get("delay",3)
        if (t := chk.get("timeout", None)) is not None:
            self.delay[tm]=t

    async def _run_dest(self, errs):
        async for pt in self.dest:
            try:
                cv = await self.conn.d_get(pt.chk["copied"]["at"])
                v = get_p(cv,pt.chk["copied"]["item"])
                if v != pt.v:
                    raise ValueError("want {pt.v}, got {v}")
            except Exception as exc:
                # only set the error if there isn't one already
                try:
                    if "want " in errs.get(pt.p, create=False).data.msg:
                        continue
                except (AttributeError,KeyError):
                    pass
                await self.conn.e_exc(pt.p,"Comparison",exc)
            else:
                # only clear the error if there is one
                try:
                    errs.get(pt.p, create=False).data.msg
                except (ValueError,KeyError,AttributeError):
                    pass
                else:
                    await self.conn.e_ok(pt.p)

    async def _run_delay(self, errs):
        async for pt in self.delay:
            await self.conn.e_info(err_p, e_msg, check=chk,data=v)

    async def run(self):
        async with (
            self.conn.d_watch(P("flow"), state=None, subtree=True).node() as flows,
            self.conn.d_watch(P("error.flow")+self.path, state=None, subtree=True).node() as errs,
            self.conn.d_watch(self.path, state=None, subtree=True, meta=True) as data,
            anyio.create_task_group() as tg,
        ):
            # TODO this is not quite correct, need to do it explicitly
            # because if an error is resolved we need to update the stored value

            async for pdm in data:
                if pdm is None:
                    # Marker: start processing timeouts
                    tg.start_soon(self._run_dest, errs)
                    tg.start_soon(self._run_delay, errs)
                    continue
                p,d,m = pdm
                try:
                    flow = flows.search(self.path+pp)
                except KeyError:
                    continue
                try:
                    err_d = errs[p]
                except KeyError:
                    err_d = None

                for pp,chk in _gen_paths(flow.data):
                    if len(pp):
                        err_path = p/None+pp
                    else:
                        err_path=p

                    if err_d is not None and len(pp):
                        try:
                            err_pp = err_d[None][pp]
                        except KeyError:
                            err_pp = None
                    else:
                        err_pp = err_d

                    # if d is NotGiven, the item has been deleted
                    if d is NotGiven:
                        v = NotGiven
                    else:
                        try:
                            v = get_p(flow.data, pp)
                        except KeyError:
                            v = NotGiven

                    e_msg = None
                    if v is not NotGiven:
                        e_msg = self.check_data(v, chk, m)
                    elif chk.get("required", False):
                        e_msg = "Missing data"

                    if e_msg is not None:
                        # TODO skip if the message isn't modified
                        try:
                            if err_pp.data.msg == e_msg:
                                continue
                        except (ValueError,AttributeError):
                            pass  # data deleted
                        await self.conn.e_info(err_path, e_msg, check=chk,data=v)
                    elif err_pp is not None:
                        await self.conn.e_ok(err_path)



@cli.command()
@click.argument("path", type=P, nargs=1, default=P("state"))
@click.pass_obj
async def monitor(obj, path):
    """
    Monitor a subtree and report flow errors.
    """
    flow = FlowMon(obj.conn, path)
    await flow.run()


@cli.command()
@click.option("-v", "--verbose", is_flag=True, help="Report incoming states.")
@click.option("-m", "--monitor", is_flag=True, help="Continue monitoring.")
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def check(obj, path, verbose, monitor):
    """
    Check stored messages in a subtree against flows.
    Does not check or trigger errors; does not verify timeouts
    (but reports stale data).
    """
    n_bad = 0
    n_skip = 0
    n_good = 0

    async with (
        obj.conn.d_watch(P("flow"), state=None, subtree=True).node() as flows,
        obj.conn.d_watch(self.path,
                         state=None if monitor else True, subtree=True,meta=True) as data,
    ):
        async for p,d,m in data:
            try:
                flow = flows.get_(path+p).data
            except KeyError:
                n_skip += 1
            else:
                pass # TODO verify

            if d is NotGiven:
                if flow.get("_",{}).get("required",False):
                    n_bad += 1
                    print("DEL",p)
            else:
                if (t := flow.get("_",{}).get("timeout",-1)) > 0:
                    if time.time()-m.timestamp > t:
                        print("OLD",p)
                        n_bad += 1

                for pp,chk in _gen_paths(flow):
                    try:
                        v = d.get_(pp)
                    except KeyError:
                        if chk.get("required",False):
                            n_bad += 1
                            print("MIS",p,pp)
                            break
                    else:
                        if (s := _check_limits(v,chk)) is not None:
                            n_bad += 1
                            print("CHK",p,pp,s)
                        else:
                            n_good += 1
            if verbose:
                print(" ",n_good,n_skip,n_bad,p,"     ", end="\r")
                sys.stdout.flush()
