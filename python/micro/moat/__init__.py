from moat.patch import _patch
_patch()
del _patch

from moat._main import moat_run

def spawn(evt,p,*a,**k):
	import uasyncio
	import sys
	async def catch():
		try:
			await p(*a,**k)
		except Exception as exc:
			evt.set()
			sys.print_exception(exc)
	uasyncio.create_task(catch())
