# command line interface
from __future__ import annotations

import anyio
import time
from contextlib import suppress

import asyncclick as click
from attrs import define, field

from moat.util import NotGiven, get_part, yprint
from moat.lib.path import P, Path
from moat.lib.priomap import TimerMap
from moat.link.client import Link

from collections.abc import Iterator, Mapping
from typing import Any, cast


@click.group(short_help="Manage data flows.")
@click.pass_context
async def cli(ctx):
    """
    This subcommand reads data flow controls stored in the MoaT-Link service.
    """
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg, common=True))


def flow_path(path: Path) -> Path:
    """
    Return the flow-check lookup path for a data path.
    """
    return P("flow") + path


def _error_path(path: Path, rel: Path) -> Path:
    """
    Return the error path for a checked data sub-item.
    """
    if len(rel) == 0:
        return path
    return path / None + rel


def _iter_checks(data: Any, base: Path = Path()) -> Iterator[tuple[Path, Mapping[str, Any]]]:
    """
    Yield check definitions in a flow config tree.
    """
    if not isinstance(data, Mapping):
        return

    check = data.get("_")
    if isinstance(check, Mapping):
        yield base, check

    for key, value in data.items():
        if key == "_":
            continue
        if not isinstance(key, (str, int)):
            continue
        yield from _iter_checks(value, base / key)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _check_limits(value: Any, check: Mapping[str, Any], previous: Any = NotGiven) -> str | None:
    """
    Validate min/max/maxstep limits.
    """
    num = _as_float(value)
    if (v_min := check.get("min", None)) is not None:
        if num is None:
            return "Value is not numeric"
        if num < float(v_min):
            return f"{num:g} < {float(v_min):g}"

    if (v_max := check.get("max", None)) is not None:
        if num is None:
            return "Value is not numeric"
        if num > float(v_max):
            return f"{num:g} > {float(v_max):g}"

    if (v_step := check.get("maxstep", None)) is not None and previous is not NotGiven:
        prev_num = _as_float(previous)
        if num is not None and prev_num is not None:
            delta = abs(num - prev_num)
            if delta > float(v_step):
                return f"Step {delta:g} > {float(v_step):g}"

    return None


async def _check_copied(conn: Link, value: Any, check: Mapping[str, Any]) -> str | None:
    """
    Validate a ``copied`` rule.
    """
    copied = check.get("copied", None)
    if not isinstance(copied, Mapping):
        return None

    if "at" not in copied:
        return "Copied rule has no destination path"

    try:
        c_val = await conn.d_get(copied["at"])
    except Exception as exc:
        return f"Copied lookup failed: {exc}"

    c_item = copied.get("item", None)
    if c_item is not None:
        try:
            c_val = get_part(c_val, c_item)
        except Exception as exc:
            return f"Copied item lookup failed: {exc}"

    if c_val != value:
        return f"Copied mismatch: want {value!r}, got {c_val!r}"
    return None


def _flow_for(flows: Any, path: Path) -> Mapping[str, Any] | None:
    try:
        flow = flows.search(path).data
    except (KeyError, ValueError):
        return None
    if not isinstance(flow, Mapping):
        return None
    return flow


async def _check_path(
    conn: Link,
    *,
    path: Path,
    data: Any,
    meta: Any,
    flow: Mapping[str, Any],
    previous: dict[Path, Any],
    now: float,
    do_copied: bool,
    do_stale_age: bool = True,
    queue_copied: bool = False,
) -> tuple[
    set[Path],
    dict[Path, tuple[str, Mapping[str, Any], Any]],
    dict[Path, tuple[float, Mapping[str, Any], Any]],
    dict[Path, tuple[float, Mapping[str, Any], Any]],
]:
    """
    Evaluate one message against flow rules.
    """
    checked: set[Path] = set()
    errors: dict[Path, tuple[str, Mapping[str, Any], Any]] = {}
    timeouts: dict[Path, tuple[float, Mapping[str, Any], Any]] = {}
    copied: dict[Path, tuple[float, Mapping[str, Any], Any]] = {}

    for rel, check in _iter_checks(flow):
        err_p = _error_path(path, rel)
        checked.add(err_p)

        if data is NotGiven:
            if check.get("required", False):
                errors[err_p] = ("Missing data", check, NotGiven)
            continue

        try:
            if len(rel) == 0:
                value = data
            else:
                value = get_part(data, rel)
        except Exception:
            value = NotGiven

        if value is NotGiven:
            if check.get("required", False):
                errors[err_p] = ("Missing data", check, NotGiven)
            continue

        prev_key = path + rel
        prev_val = previous.get(prev_key, NotGiven)
        previous[prev_key] = value

        msg = _check_limits(value, check, prev_val)
        if msg is None:
            if do_copied:
                msg = await _check_copied(conn, value, check)
            elif queue_copied:
                rule = check.get("copied", None)
                if isinstance(rule, Mapping):
                    delay = rule.get("delay", 3.0)
                    try:
                        delay = float(delay)
                    except (TypeError, ValueError):
                        delay = 3.0
                    if delay < 0:
                        delay = 0.0
                    copied[err_p] = (delay, check, value)

        if msg is not None:
            errors[err_p] = (msg, check, value)

        timeout = check.get("timeout", None)
        if timeout is not None:
            try:
                timeout = float(timeout)
            except (TypeError, ValueError):
                timeout = None

        if timeout is not None and timeout > 0:
            timeouts[err_p] = (timeout, check, value)
            ts = getattr(meta, "timestamp", None)
            if do_stale_age and ts is not None and now - ts > timeout and err_p not in errors:
                age = now - ts
                errors[err_p] = (f"Stale data: {age:g}s > {timeout:g}s", check, value)

    return checked, errors, timeouts, copied


@define
class _Timeout:
    path: Path = field()
    timeout: float = field()
    check: Mapping[str, Any] = field()
    value: Any = field()
    rel: Path = field()

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other: object):
        if isinstance(other, _Timeout):
            other = other.path
        if isinstance(other, Path):
            return self.path == other
        return False


@define
class _Copied:
    path: Path = field()
    check: Mapping[str, Any] = field()
    value: Any = field()
    rel: Path = field()

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other: object):
        if isinstance(other, _Copied):
            other = other.path
        if isinstance(other, Path):
            return self.path == other
        return False


class FlowMon:
    """
    Monitor incoming messages and create flow errors.
    """

    def __init__(self, conn: Link, path: Path):
        self.conn = conn
        self.path = path
        self.previous: dict[Path, Any] = {}
        self.active_errors: dict[Path, str] = {}
        self.timeout: TimerMap[_Timeout] = TimerMap()
        self.copied: TimerMap[_Copied] = TimerMap()
        self.errs = None
        self.flows = None

    def _error_exists(self, path: Path) -> bool:
        if self.errs is None:
            return False
        try:
            self.errs[path]
        except (KeyError, ValueError):
            return False
        return True

    async def _set_error(
        self, path: Path, msg: str, check: Mapping[str, Any], data: Any, data_path: Path
    ) -> None:
        if self.active_errors.get(path, None) == msg:
            return
        self.active_errors[path] = msg
        await self.conn.e_info(
            P("flow") + self.path + path,
            msg,
            data_path=self.path + data_path,
            check=check,
            data=data,
        )

    async def _clear_error(self, path: Path) -> None:
        if path not in self.active_errors and not self._error_exists(path):
            return
        self.active_errors.pop(path, None)
        await self.conn.e_ok(P("flow") + self.path + path)

    async def _run_timeouts(self) -> None:
        async for tm in self.timeout:
            msg = f"No update for {tm.timeout:g}s"
            await self._set_error(tm.path, msg, tm.check, tm.value, tm.rel)

    async def _run_copied(self) -> None:
        async for cp in self.copied:
            msg = await _check_copied(self.conn, cp.value, cp.check)
            if msg is None:
                if self.active_errors.get(cp.path, "").startswith("Copied "):
                    await self._clear_error(cp.path)
                continue
            await self._set_error(cp.path, msg, cp.check, cp.value, cp.rel)

    async def run(self) -> None:
        """
        Run the monitor.
        """
        async with (
            self.conn.d_watch(P("flow"), state=None, subtree=True).node as flows,
            self.conn.d_watch(P("error.flow") + self.path, state=None, subtree=True).node as errs,
            self.conn.d_watch(self.path, state=None, subtree=True, meta=True) as mon,
            anyio.create_task_group() as tg,
        ):
            self.flows = flows
            self.errs = errs
            tg.start_soon(self._run_timeouts)
            tg.start_soon(self._run_copied)

            async for rel, data, meta in mon:
                flow = _flow_for(flows, self.path + rel)
                if flow is None:
                    continue

                checked, errors, timeouts, copied = await _check_path(
                    self.conn,
                    path=rel,
                    data=data,
                    meta=meta,
                    flow=flow,
                    previous=self.previous,
                    now=time.time(),
                    do_copied=False,
                    do_stale_age=False,
                    queue_copied=True,
                )

                for path in checked:
                    if path not in timeouts:
                        with suppress(KeyError):
                            del self.timeout[cast(_Timeout, path)]

                    if path not in copied:
                        with suppress(KeyError):
                            del self.copied[cast(_Copied, path)]

                for path, (timeout, check, value) in timeouts.items():
                    tm = _Timeout(path, timeout, check, value, rel)
                    self.timeout[tm] = tm.timeout

                for path, (delay, check, value) in copied.items():
                    cp = _Copied(path, check, value, rel)
                    self.copied[cp] = delay

                for path in checked:
                    if path in errors:
                        msg, check, value = errors[path]
                        await self._set_error(path, msg, check, value, rel)
                    elif path in copied:
                        if self.active_errors.get(path, "").startswith("No update for"):
                            await self._clear_error(path)
                    else:
                        await self._clear_error(path)


@cli.command()
@click.argument("path", type=P, nargs=1)
@click.pass_obj
async def get(obj, path):
    """
    Retrieve the flow-check definition for a path.
    """
    res = await obj.conn.d_search(flow_path(path))
    yprint(res, stream=obj.stdout)


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
    Check stored messages in a subtree against flow checks.

    This command does not create errors in ``error.flow``.
    """
    n_bad = 0
    n_skip = 0
    n_good = 0
    previous: dict[Path, Any] = {}
    watch_state = None if monitor else True

    async with (
        obj.conn.d_watch(P("flow"), state=None, subtree=True).node as flows,
        obj.conn.d_watch(path, state=watch_state, subtree=True, meta=True) as mon,
    ):
        async for rel, data, meta in mon:
            full = path + rel
            flow = _flow_for(flows, full)
            if flow is None:
                n_skip += 1
                continue

            checked, errors, _timeouts, _copied = await _check_path(
                obj.conn,
                path=rel,
                data=data,
                meta=meta,
                flow=flow,
                previous=previous,
                now=time.time(),
                do_copied=True,
                queue_copied=False,
            )

            n_bad += len(errors)
            n_good += len(checked) - len(errors)
            for err_path, (detail, check, value) in errors.items():
                yprint(
                    dict(
                        path=path + err_path,
                        data_path=full,
                        detail=detail,
                        check=check,
                        data=value,
                    ),
                    stream=obj.stdout,
                )
                print("---", file=obj.stdout)
                obj.stdout.flush()

            if verbose:
                click.echo(f"ok: {n_good}  skipped: {n_skip}  bad: {n_bad}", err=True)
