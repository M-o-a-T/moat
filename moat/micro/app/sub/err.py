"""
Error handler and retry app.
"""

from __future__ import annotations

from moat.lib.micro import L, log, sleep_ms
from moat.lib.rpc import BaseFwdCmd

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.lib.rpc import MsgSender


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

    TODO: exponential back-off
    """

    doc = dict(
        _c=dict(
            _d="Error catcher",
            cfg="app:sub-app to run",
            retry="int:autorestart# (0, -1=inf)",
            timeout="int:restart timer (100)",
            notify="path:call on error",
            always="bool:restart if no error",
        )
    )

    retry: int = None
    timeout: int = None
    p: MsgSender | None = None

    @property
    def cfg_name(self) -> str:
        "Human readable name"

        return (
            f"{super().cfg_name} → {self.app.cfg_name if self.app else self.cfg.get('app', '?')}"
        )

    async def handle(self, *a, **k):
        """Handle a command, waiting for ready if needed."""
        if L:
            if self.app is None:
                await super().wait_ready()
            await self.app.wait_ready()
        return await super().handle(*a, **k)

    async def reload(self):
        """Reload configuration."""
        self._load()
        await super().reload()

    def _load(self):
        self.retry = self.cfg.get("retry", 0)
        self.timeout = self.cfg.get("timeout", 100)
        self.always = self.cfg.get("always", False)

        p = self.cfg.get("notify", None)
        self.notify = self.root.sub_at(p) if p is not None else None

    if L:

        async def wait_ready(self, wait: bool = True):
            """Allow for non-restarted sub-app."""
            while res := await super().wait_ready(wait=wait):
                if not self.retry:
                    return res
                await sleep_ms(1)

            return res

    async def run_app(self):
        """
        Runs the sub-app and handles restarting and error shielding.
        """
        self._load()

        while True:
            try:
                # log("Err Run %s %r", self.path, self)
                await super().run_app()
            except Exception as exc:
                log("Err %s %r", self.path, exc, err=exc)
                if self.notify is not None:
                    try:
                        await self.notify(here=self.path, err=exc)
                    except Exception:
                        log("Err Report %s %r", self.path, exc, err=exc)

                if not self.retry:
                    if self.cfg.get("retry", 0):
                        raise
                    return
            else:
                # ends without error
                log("Err End %s %r", self.path, self.app)
                if not self.always:
                    return

            if self.retry:
                self.app.init_events()
            # otherwise dead

            if self.retry > 0:
                self.retry -= 1
            await sleep_ms(self.timeout)
