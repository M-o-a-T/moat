import anyio
from moat.lib.cmd import CmdHandler
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def scaffold(ha,hb):
	
	async def cp(src,dst, d):
		while True:
			msg = await src.msg_out()
			logger.debug("%s %r",d,msg)
			await dst.msg_in(msg)

	async with (
			anyio.create_task_group() as tg,
			CmdHandler(ha) as a,
			CmdHandler(hb) as b,
		):
		tg.start_soon(cp,a,b,">")
		tg.start_soon(cp,b,a,"<")
		yield a,b,tg
		tg.cancel_scope.cancel()
		assert not a._in, a._in
		assert not b._in, b._in
		assert not a._out, a._out
		assert not b._out, b._out
