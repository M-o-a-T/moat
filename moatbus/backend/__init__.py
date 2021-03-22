#
"""
Base class for sending MoaT messages on a Trio system
"""

import asyncclick as click
from contextlib import asynccontextmanager
from distkv.util import P

from ..message import BusMessage
from ..util import CtxObj

class UnknownParamError(RuntimeError):
    pass

class MissingParamError(RuntimeError):
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
    short_help=None
    need_host = False

    PARAMS = {}
    # name: type checker default

    @classmethod
    def repr(cls, cfg: dict):
        return " ".join(f"{k}:{v}" for k,v in dict.items())

    @classmethod
    def check_config(cls, cfg: dict):
        for k,v in cfg.items():
            try:
                x = cls.PARAMS[k]
            except KeyError:
                raise UnknownParamError(k)
            else:
                t,i,c,d,m = x
                if not c(v):
                    raise RuntimeError(f"Wrong parameter {k}: {m}")

        for n,x in cls.PARAMS.items():
            if n in cfg:
                continue
            t,i,c,d,m = x
            if d is None:
                import pdb;pdb.set_trace()
                tn = "Path" if t is P else t.__name__
                raise click.MissingParameter(param_hint="", param_type=f"{tn} parameter: {n}")
            if n not in cfg:
                cfg[n] = d

    def __init__(self):
        pass

    @asynccontextmanager
    async def _ctx(self):
        yield self

    async def send(self, msg:BusMessage):
        raise RuntimeError("Override @send!")

    def __aiter__(self):
        raise RuntimeError("Override @__aiter__!")

    async def __anext__(self):
        raise RuntimeError("Override @__anext__!")
