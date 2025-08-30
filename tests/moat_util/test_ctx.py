"""
More util functions
"""

from __future__ import annotations

from moat.util.ctx import ContextMgr
import pytest
import anyio

from contextlib import asynccontextmanager

@pytest.mark.anyio
async def test_context():
    class Ctx(ContextMgr):
        i=0
        @asynccontextmanager
        async def context(self, i=None):
            self.i = self.i+1 if i is None else i
            yield self.i

    async with anyio.create_task_group() as tg:
        ctx = Ctx()
        tg.start_soon(ctx.task)
        assert ctx.ctx is None

        await ctx.start()
        assert ctx.ctx == 1
        await ctx.stop()
        assert ctx.ctx is None

        await ctx.start(4)
        assert ctx.ctx == 4
        await ctx.stop()
        assert ctx.ctx is None
        
        ctx.close()

@pytest.mark.anyio
async def test_context_timeout():
    class Ctx(ContextMgr):
        timeout = False

        @asynccontextmanager
        async def context(self, t):
            self.timeout = False
            await anyio.sleep(t)
            try:
                yield True
            except TimeoutError:
                self.timeout = True

    async with anyio.create_task_group() as tg:
        ctx = Ctx()
        tg.start_soon(ctx.task)

        # time out starting
        with pytest.raises(TimeoutError), anyio.fail_after(.1):
            await ctx.start(.2)
        assert ctx.ctx is None
        assert not ctx.timeout

        # time out the context
        try:
            with anyio.fail_after(.2):
                await ctx.start(.1)
                await anyio.sleep(.2)
        except TimeoutError as exc:
            await ctx.stop(exc)
        else:
            assert False,"timeout not raised"
        assert ctx.ctx is None
        assert ctx.timeout

        ctx.close()
