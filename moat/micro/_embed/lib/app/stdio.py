"""
Console stdio access
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from moat.micro.cmd.stream import BaseBBMCmd, StreamCmd
from moat.micro.stacks.console import console_stack
from moat.micro.part.serial import Serial

class StdioBuf(FileBuf):
    @asynccontextmanager
    async def stream(self):
        yield sys.stdin.buffer,sys.stdout.buffer

class StdIO(StreamCmd):
    """Sends/receives MoaT messages using stdin/stdout"""
    @asynccontextmanager
    async def stream(self):
        import sys
        p = 
        async with console_stack(Serial(self.cfg), self.cfg) as stream:


        async def run_console(force_write=False):
            import micropython

            from moat.micro.stacks.console import console_stack

            micropython.kbd_intr(-1)
            try:
                in_b = sys.stdin.buffer
                out_b = sys.stdout.buffer
                from moat.micro.proto.stream import AsyncStream

                s = AsyncStream(in_b, out_b, force_write=force_write)
            except AttributeError:  # on Unix
                from moat.micro.proto.fd import AsyncFD

                s = AsyncFD(sys.stdin, sys.stdout)
            t, b = await console_stack(
                s,
                ready=ready,
                lossy=cfg["link"]["lossy"],
                log=log,
                msg_prefix=0xC1 if cfg["link"]["guarded"] else None,
                use_console=cfg["link"].get("console", False),
            )
            t = t.stack(StdBase, fallback=fallback, state=state, cfg=cfg)
            await tg.spawn(b.run, _name="runcons")

