"""
Apps used for structure.
"""

from __future__ import annotations

from moat.micro.cmd.array import ArrayCmd
from moat.micro.cmd.tree import BaseFwdCmd, DirCmd

try:
    from moat.micro.proto.stream import ProcessDeadError
except ImportError:  # satellite

    class ProcessDeadError(Exception):
        "dummy"


from moat.micro.compat import log, sleep_ms


class Tree(DirCmd):
    """
    Structured subcommands.
    """


class Array(ArrayCmd):
    """
    List of mostly-same things.
    """


class Err(BaseFwdCmd):
    """
    An error handler and possibly-retrying subcommand manager.

    This handler catches some retryable exceptions, thus shielding the rest
    of MoaT from them.

    If the @retry config is zero the exception is ignored, otherwise the
    app is restarted after a timeout.

    Set @retry to -1 for infinite retries.

    Set @always to `True` if the app should be restarted if it ends without
    raising an error.

    Errors caught:
    * OSError
    * EOFError
    * ProcessDeadError

    TODO: exponential back-off
    """

    _wait = True

    r: int = None
    t: int = None
    a: bool = None

    async def dispatch(self, *a, **k):  # noqa:D102
        if self.app is None:
            await super().wait_ready()
        await self.app.wait_ready()
        return await super().dispatch(*a, **k)

    async def reload(self):  # noqa:D102
        self._load()
        await super().reload()

    def _load(self):
        self.r = self.cfg.get("retry", 0)
        self.t = self.cfg.get("timeout", 100)
        self.a = self.cfg.get("always", False)

    async def run_app(self):
        """
        Runs the sub-app and handles restarting and error shielding.
        """
        log("Fwd Start %s", self.path)
        self._load()

        self._wait = self.cfg.get("wait", True)
        while True:
            try:
                log("Fwd Run %s %r", self.path, self)
                await super().run_app()
            except (OSError, ProcessDeadError, EOFError) as exc:
                log("Fwd Err %s %r", self.path, exc)
                if not self.r:
                    if self.cfg.get("retry", 0):
                        raise
                    return
            else:
                # ends without error
                log("Fwd End %s %r", self.path, self.app)
                if not self.a or not self.r:
                    return
            if self.r > 0:
                self.r -= 1
            try:
                await sleep_ms(self.t)
            except BaseException as exc:
                log("Fwd ErrX %s %r", self.path, exc)
                raise
