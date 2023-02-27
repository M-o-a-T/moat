import io
import os
import msgpack
import hashlib
from pathlib import Path

import anyio
from anyio_serial import Serial
from contextlib import asynccontextmanager

from moat.micro.path import copytree
from moat.micro.stacks import console_stack
from moat.micro.compat import TaskGroup, AnyioMoatStream
from moat.util import attrdict, yload
from moat.micro.cmd import ClientBaseCmd

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
async def get_serial(obj):
	"""\
		Context: the specified serial port.

		Returns an anyio stream.

		NB this cycles RTS and flushes data.
		"""
	if not obj.port:
		raise NoPort("No port given")
	_h={}
	try:
		_h['baudrate'] = obj.baudrate
	except AttributeError:
		pass
	ser = Serial(obj.port, **_h)
	async with ser:
		# clear DTR+RTS. May reset the target.
		ser.rts = True
		ser.dtr = False
		await anyio.sleep(0.1)
		ser.rts = False

		# flush messages
		while True:
			with anyio.move_on_after(0.2):
				res = await ser.receive(200)
				logger.debug("Flush: %r", res)
				continue
			break
		yield ser


@asynccontextmanager
async def get_link_serial(obj, ser, ignore=False, **kw):
	"""\
		Context: Link to the target using the serial port @ser and a
		console-ish stack.

		Returns the top stream.
		"""
	t,b = await console_stack(AnyioMoatStream(ser), log=obj.debug>2, reliable=not obj.reliable, console=0xc1 if obj.guarded else False, **kw)
	if ignore:
		t.ignore_hooks()

	async with TaskGroup() as tg:
		task = await tg.spawn(b.run)
		try:
			yield t
		finally:
			task.cancel()


@asynccontextmanager
async def get_link(obj, ignore=False, use_port=False, reset=False, **kw):
	"""\
		Context: Link to the target: the Unix-domain socket, if that can be
		connected to, or the serial port.

		Returns the top MoaT stream.
		"""
	try:
		if obj.socket:
			sock = await anyio.connect_unix(obj.socket)
		else:
			raise AttributeError("socket")
	except (AttributeError,OSError):
		if not use_port:
			raise
		async with get_serial(obj, reset=reset, flush=True) as ser:
			async with get_link_serial(obj,ser, ignore=ignore, **kw) as link:
				yield link
	else:
		try:
			t,b = await console_stack(AnyioMoatStream(sock), log=obj.debug>2, reliable=True, **kw)
			if ignore:
				t.ignore_hooks()
			async with TaskGroup() as tg:
				task = await tg.spawn(b.run)
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
			t,b = await console_stack(AnyioMoatStream(sock), log=obj.debug>2, reliable=True, **kw)
			async with TaskGroup() as tg:
				task = await tg.spawn(b.run)
				yield t
				task.cancel()
		finally:
			await sock.aclose()

async def get_cfg(req):
	"""\
		Collect the client's configuration data.
		"""
	async def _get_cfg(p):
		d = await req.send(("sys","cfg"),p=p)
		if isinstance(d,(list,tuple)):
			d,s = d
			for k in s:
				d[k] = await _get_cfg(p+(k,))
		return d

	return await _get_cfg(())

# There is no "set_cfg" because you do this by uploading the msgpack'd
# config file, then calling sys.cfg_r on it. Or by sending config snippets.
