#
"""
Base class for sending MoaT messages on a Trio system
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncclick as click

from moat.bus.util import CtxObj
from moat.lib.path import P

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.bus.message import BusMessage

    from collections.abc import AsyncIterator


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

    short_help: str | None = None
    need_host: bool = False

    PARAMS: dict[str, tuple[Any, str, Any, Any, str]] = {}
    # name: type checker default

    @classmethod
    def repr(cls, cfg: dict[str, Any]) -> str:
        """Render a config dict as a string."""
        return " ".join(f"{k}:{v}" for k, v in cfg.items())

    @classmethod
    def check_config(cls, cfg: dict[str, Any]) -> None:
        """Validate configuration parameters."""
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

    def __init__(self, client: Any = None) -> None:
        pass

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[BaseBusHandler]:
        yield self

    async def send(self, msg: BusMessage) -> None:
        """Send a message on the bus."""
        msg  # noqa:B018
        raise RuntimeError("Override @send!")

    def __aiter__(self) -> BaseBusHandler:
        raise RuntimeError("Override @__aiter__!")

    async def __anext__(self) -> BusMessage:
        raise RuntimeError("Override @__anext__!")
