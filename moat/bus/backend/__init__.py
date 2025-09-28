#
"""
Base class for sending MoaT messages on a Trio system
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncclick as click
from distkv.util import P

from moat.bus.util import CtxObj

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.bus.message import BusMessage


class UnknownParamError(RuntimeError):
    "Don't know this"
    pass


class MissingParamError(RuntimeError):
    "Want to know this"
    pass


class BaseBusHandler(CtxObj):
    """
    This class defines the (common methods for an) interface for exchanging
    MoaT messages.

    Usage::

        async with moatbus.backend.NAME.Handler(**params) as bus:
            await bus.send(some_msg)
            async for msg in bus:
                await process(msg)
    """

    short_help = None
    need_host = False

    PARAMS = {}
    # name: type checker default

    @classmethod
    def repr(cls, cfg: dict):  # noqa:D102
        cfg # noqa:B018
        return " ".join(f"{k}:{v}" for k, v in dict.items())

    @classmethod
    def check_config(cls, cfg: dict):  # noqa:D102
        for k, v in cfg.items():
            try:
                x = cls.PARAMS[k]
            except KeyError:
                raise UnknownParamError(k) from None
            else:
                t, _i, c, d, m = x
                if not c(v):
                    raise RuntimeError(f"Wrong parameter {k}: {m}")

        for n, x in cls.PARAMS.items():
            if n in cfg:
                continue
            t, _i, c, d, m = x
            if d is None:
                tn = "Path" if t is P else t.__name__
                raise click.MissingParameter(param_hint="", param_type=f"{tn} parameter: {n}")
            if n not in cfg:
                cfg[n] = d

    def __init__(self, client):
        pass

    @asynccontextmanager
    async def _ctx(self):
        yield self

    async def send(self, msg: BusMessage):  # noqa:D102
        msg  # noqa:B018
        raise RuntimeError("Override @send!")

    def __aiter__(self):
        raise RuntimeError("Override @__aiter__!")

    async def __anext__(self):
        raise RuntimeError("Override @__anext__!")
