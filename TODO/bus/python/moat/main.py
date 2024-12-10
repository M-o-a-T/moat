import io
import os
import msgpack
import hashlib
from pathlib import Path

import anyio
from anyio_serial import Serial
from contextlib import asynccontextmanager
import asyncclick as click

from moat.path import copytree
from moat.stacks import console_stack
from moat.compat import TaskGroup, UAStream
from moat.util import attrdict, yload
from moat.cmd import ClientBaseCmd

import logging
logger = logging.getLogger(__name__)


class ABytes(io.BytesIO):
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

def add_client_hooks(req):
	bc = req.stack(ClientBaseCmd)
	bc.cmd_link = lambda _:0

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
		Open the specified serial port.
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
		# flush old messages
		try:
			while True:
				with anyio.fail_after(0.2):
					b = await ser.receive(1)
		except TimeoutError:
			# more might arrive later, but we'll ignore them
			# because our sequence# returns to 10, not zero
			pass
		yield ser


@asynccontextmanager
async def get_link_serial(obj, ser, **kw):
	"""\
		Link to the target using this serial port.
		"""
	t,b = await console_stack(UAStream(ser), log=obj.verbose>2, reliable=not obj.reliable, console=0xc1 if obj.guarded else False, **kw)
	async with TaskGroup() as tg:
		task = await tg.spawn(b.run)
		try:
			yield t
		finally:
			task.cancel()


@asynccontextmanager
async def get_link(obj, use_port=False, **kw):
	"""\
		Link to the target: the socket, if that can be connected to,
		or the serial port.
		"""
	try:
		if obj.socket:
			sock = await anyio.connect_unix(obj.socket)
		else:
			raise AttributeError("socket")
	except (AttributeError,OSError):
		if not use_port:
			raise
		async with get_serial(obj) as ser:
			async with get_link_serial(obj,ser, **kw) as link:
				yield link
	else:
		try:
			t,b = await console_stack(UAStream(sock), log=obj.verbose>2, reliable=True, **kw)
			async with TaskGroup() as tg:
				task = await tg.spawn(b.run)
				yield t
				task.cancel()
		finally:
			await sock.aclose()


@click.group()
@click.pass_context
@click.option("-c","--config", help="Configuration file (YAML)", type=click.Path(dir_okay=False,readable=True))
@click.option("-s","--socket", help="Socket to use / listen to when multiplexing (cfg.port.socket)", type=click.Path(dir_okay=False,writable=True,readable=True))
@click.option("-p","--port", help="Port your µPy device is connected to (cfg.port.dev)", type=click.Path(dir_okay=False,writable=True,readable=True,exists=True))
@click.option("-b","--baudrate", type=int, default=115200, help="Baud rate to use (cfg.port.rate)")
@click.option("-v","--verbose", count=True, help="Be more verbose")
@click.option("-q","--quiet", count=True, help="Be less verbose")
@click.option("-R","--reliable", is_flag=True, help="Use Reliable mode, wrap messages in SerialPacker frame (cfg.port.reliable)")
@click.option("-g","--guarded", is_flag=True, help="Use Guard mode (prefix msgpack with 0xc1 byte, cfg.port.guard)")
async def main(ctx, socket,port,baudrate,verbose,quiet,reliable,guarded, config):
	ctx.ensure_object(attrdict)
	obj=ctx.obj
	if config:
		with open(config,"r") as f:
			cfg = yload(f, attr=True)
	else:
		cfg = attrdict()
	obj.cfg = cfg

	try:
		cfg.port
	except AttributeError:
		cfg.port = attrdict()
	try:
		if socket:
			cfg.port.socket = socket
		else:
			socket = cfg.port.socket
	except AttributeError:
		pass
	try:
		if port:
			cfg.port.dev = port
		else:
			port = cfg.port.dev
	except AttributeError:
		pass
	try:
		if baudrate:
			cfg.port.rate = baudrate
			baudrate = cfg.port.rate
	except AttributeError:
		pass
	try:
		if reliable:
			cfg.port.reliable = reliable
		else:
			reliable = cfg.port.reliable
	except AttributeError:
		pass
	try:
		if guarded:
			cfg.port.guarded = guarded
		else:
			guarded = cfg.port.guarded
	except AttributeError:
		pass

	obj.verbose = verbose+1-quiet
	logging.basicConfig(level=logging.DEBUG if obj.verbose>2 else logging.INFO if obj.verbose>1 else logging.WARNING if obj.verbose>0 else logging.ERROR)

	if not os.path.isabs(socket):
		socket = os.path.join(os.environ.get("XDG_RUNTIME_DIR","/tmp"), socket)
	obj.socket=socket
	obj.port=port
	if baudrate:
		obj.baudrate=baudrate
	if reliable and guarded:
		raise click.UsageError("Reliable and Guarded mode don't like each other")
	obj.reliable=reliable
	obj.guarded=guarded
