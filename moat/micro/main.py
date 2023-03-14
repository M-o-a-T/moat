import io
import os
import msgpack
import hashlib
from pathlib import Path

import anyio
from anyio_serial import Serial
from contextlib import asynccontextmanager

from moat.micro.path import copytree
from moat.micro.stacks.console import console_stack
from moat.micro.compat import TaskGroup, AnyioMoatStream
from moat.util import attrdict, yload, packer
from moat.micro.cmd import ClientBaseCmd, Request as BaseRequest

import logging
logger = logging.getLogger(__name__)


class ABytes(io.BytesIO):
	"""
	An async-IO-mimicing version of `io.BytesIO`.
	"""
	def __init__(self, name, data):
		super().__init__()
		self.name = name
		self.write(data)
		self.suffix = Path(name).suffix

	def __str__(self):
		return str(self.name)

	async def open(self, mode):
		self.seek(0,0)
		return self
	
	async def read_bytes(self):
		return self.getbuffer()

	async def sha256(self):
		_h = hashlib.sha256()
		_h.update(self.getbuffer())
		return _h.digest()  

	def close(self):
		pass

	async def is_dir(self):
		return False

	async def is_file(self):
		return True

	async def stat(self):
		res = attrdict()
		res.st_size = len(self.getbuffer())
		return res


class NoPort(RuntimeError):
	pass

async def copy_over(src, dst, cross=None):
	tn = 0
	if await src.is_file():
		if await dst.is_dir():
			dst /= src.name
	while (n := await copytree(src,dst, cross=cross)):
		tn += n
		if n == 1:
			logger.info("One file changed. Verifying.")
		else:
			logger.info(f"{n} files changed. Verifying.")
	logger.info("Done. No (more) differences detected.")
	return tn


@asynccontextmanager
async def get_serial(obj, reset:bool = False, flush:bool = True):
	"""\
		Context: the specified serial port, as an an AnyIO stream.

		This code clears RTS and DTR.
		"""
	if not obj.port:
		raise NoPort("No port given")
	_h={}
	try:
		_h['baudrate'] = obj.baudrate
	except AttributeError:
		pass
#	if not reset:
#		_h["rts"] = False
#		_h["dtr"] = False
	ser = Serial(obj.port, **_h)
	async with ser:
		# clear DTR+RTS. May reset the target.
		if reset:
			ser.rts = True
			ser.dtr = False
			await anyio.sleep(0.1)
			ser.rts = False

		# flush messages
		if flush:
			while True:
				with anyio.move_on_after(0.2):
					res = await ser.receive(200)
					logger.debug("Flush: %r", res)
					continue
				break
		yield ser


@asynccontextmanager
async def get_link_serial(obj, ser, **kw):
	"""\
		Context: Link to the target using the serial port @ser and a
		console-ish stack.

		Returns the top stream.
		"""
	kw.setdefault("log", obj.debug>2)
	kw.setdefault("lossy", obj.lossy)

	t,b = await console_stack(AnyioMoatStream(ser), msg_prefix=0xc1 if obj.guarded else None, **kw)

	async with TaskGroup() as tg:
		task = await tg.spawn(b.run, _name="ser")
		try:
			yield t
		finally:
			task.cancel()


@asynccontextmanager
async def get_link(obj, use_port=False, reset=False, **kw):
	"""\
		Context: Link to the target: the Unix-domain socket, if that can be
		connected to, or the serial port.

		Returns the top MoaT stream.
		"""
	kw.setdefault("log", obj.debug>2)
	kw.setdefault("lossy", False)

	try:
		if obj.socket:
			sock = await anyio.connect_unix(obj.socket)
		else:
			raise AttributeError("socket")
	except (AttributeError,OSError):
		if not use_port:
			raise
		async with get_serial(obj, reset=reset, flush=True) as ser:
			async with get_link_serial(obj,ser, **kw) as link:
				yield link
	else:
		try:
			t,b = await console_stack(AnyioMoatStream(sock), **kw)
			t = t.stack(ClientBaseCmd)
			async with TaskGroup() as tg:
				task = await tg.spawn(b.run, _name="link")
				yield t
				task.cancel()
		finally:
			await sock.aclose()


@asynccontextmanager
async def get_remote(obj, host, port=27587, **kw):
	"""\
		Context: Link to a network target: host+port

		Returns the top MoaT stream.
		"""
	async with await anyio.connect_tcp(host, port) as sock:
		try:
			t,b = await console_stack(AnyioMoatStream(sock), log=obj.debug>2, lossy=False, **kw)
			async with TaskGroup() as tg:
				task = await tg.spawn(b.run, _name="rem")
				yield t
				task.cancel()
		finally:
			await sock.aclose()

class Request(BaseRequest):
	def __init__(self, *a, cmd_cls = ClientBaseCmd, **k):
		super().__init__(*a,**k)
		self.stack(cmd_cls)

	async def get_cfg(self):
		"""\
			Collect the client's configuration data.
			"""
		async def _get_cfg(p):
			d = await self.send(("sys","cfg"),p=p)
			if isinstance(d,(list,tuple)):
				d,s = d
				for k in s:
					d[k] = await _get_cfg(p+(k,))
			return d

		return await _get_cfg(())

	async def set_cfg(self, cfg):
		"""\
			Update the client's configuration data.
			"""
		async def _set_cfg(p,c):
			if isinstance(c,dict):
				if p:
					await self.send(("sys","cfg"),p=p,d={})
				for k,v in c.items():
					await _set_cfg(p+(k,),v)
			else:
				await self.send(("sys","cfg"),p=p,d=c)

		await _set_cfg((),cfg)
		await self.send(("sys","cfg"),p=None,d=None)  # runs

