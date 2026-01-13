"""
Apps used for structure.
"""

from __future__ import annotations

from moat.lib.micro import L, log, sleep_ms

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import MsgSender


def Dir(*a, **k):
    """
    Plain subcommands.
    """
    from moat.lib.rpc import DirCmd  # noqa: PLC0415

    class _Dir(DirCmd):
        pass

    return _Dir(*a, **k)


def Array(*a, **k):
    """
    List of mostly-same things.
    """
    from moat.lib.rpc import ArrayCmd  # noqa: PLC0415

    class _Array(ArrayCmd):
        pass

    return _Array(*a, **k)


def Err(*a, **k):
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

    from moat.lib.rpc import BaseFwdCmd  # noqa: PLC0415

    class _Err(BaseFwdCmd):
        _wait = True

        r: int = None
        t: int = None
        a: bool = None
        p: MsgSender | None = None

        async def handle(self, *a, **k):
            if L:
                if self.app is None:
                    await super().wait_ready()
                await self.app.wait_ready()
            return await super().handle(*a, **k)

        async def reload(self):
            self._load()
            await super().reload()

        def _load(self):
            self.r = self.cfg.get("retry", 0)
            self.t = self.cfg.get("timeout", 100)
            self.a = self.cfg.get("always", False)

            p = self.cfg.get("path", None)
            self.p = self.root.sub_at(p) if p is not None else None

        if L:

            async def wait_ready(self, wait: bool = True):
                "allow for non-restarted sub-app"
                while res := await super().wait_ready(wait=wait):
                    if not self.r:
                        return res
                    await sleep_ms(1)

                return res

        async def run_app(self):
            """
            Runs the sub-app and handles restarting and error shielding.
            """
            self._load()

            self._wait = self.cfg.get("wait", True)
            while True:
                try:
                    log("Err Run %s %r", self.path, self)
                    await super().run_app()
                except Exception as exc:
                    log("Err Err %s %r", self.path, exc, err=exc)
                    if self.p is not None:
                        try:
                            await self.p(here=self.path, err=exc)
                        except Exception:
                            log("Err Report %s %r", self.path, exc, err=exc)

                    if not self.r:
                        if self.cfg.get("retry", 0):
                            raise
                        return
                else:
                    # ends without error
                    log("Err End %s %r", self.path, self.app)
                    if not self.a or not self.r:
                        return

                if self.r:
                    self.app.init_events()
                # otherwise dead

                if self.r > 0:
                    self.r -= 1
                await sleep_ms(self.t)

    return _Err(*a, **k)
