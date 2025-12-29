"""RPC infrastructure for remote REPL access."""

from __future__ import annotations

import inspect

from moat.lib.rpc import MsgHandler

TYPE_CHECKING = False

if TYPE_CHECKING:
    from .console import Console


class MsgConsole(MsgHandler):
    """
    RPC handler that wraps a Console instance and exposes its methods via cmd_* handlers.

    This allows remote access to console operations via the MsgSender interface.
    """

    def __init__(self, console: Console):
        self.console = console

        for k in dir(console):
            if k[0] == "_":
                continue
            try:
                v = getattr(console, k)
            except AttributeError:
                continue
            if inspect.iscoroutinefunction(v):
                setattr(self, f"cmd_{k}", v)
