#!/usr/bin/env python3

import os
import sys

import msgpack
import importlib

import anyio
import asyncclick as click
from contextlib import asynccontextmanager

from .direct import DirectREPL
from .path import MoatDevPath, MoatFSPath
from .compat import TaskGroup
from .proto.multiplex import Multiplexer
from .proto import RemoteError
from .main import ABytes, NoPort, copy_over, add_client_hooks
from .main import get_serial, get_link, get_link_serial, get_remote

from moat.util.main import load_subgroup
from moat.util import attrdict, as_service, P, attr_args, process_args, yprint, yload

import logging
logger = logging.getLogger(__name__)


def clean_cfg(cfg):
	# cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
	return cfg

@load_subgroup(prefix="moat.util")
@click.pass_obj
@click.option("-c","--config", help="Configuration file (YAML)", type=click.Path(dir_okay=False,readable
=True))
@click.option("-s","--socket", help="Socket to use / listen to when multiplexing (cfg.port.socket)", type=click.Path(dir_okay=False,writable=True,readable=True))
@click.option("-p","--port", help="Port your µPy device is connected to (cfg.port.dev)", type=click.Path(dir_okay=False,writable=True,readable=True,exists=True))
@click.option("-b","--baudrate", type=int, default=115200, help="Baud rate to use (cfg.port.rate)")
@click.option("-R","--reliable", is_flag=True, help="Use Reliable mode, wrap messages in SerialPacker frame (cfg.port.reliable)")
@click.option("-g","--guarded", is_flag=True, help="Use Guard mode (prefix msgpack with 0xc1 byte, cfg.port.guard)")
async def cli(obj, socket,port,baudrate,reliable,guarded, config):
	"""MicroPython satellites"""
	cfg = obj.cfg.micro

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


@cli.command(short_help='Copy MoaT to MicroPython')
@click.pass_obj
@click.option("-n","--no-run", is_flag=True, help="Don't run MoaT after updating")
@click.option("-N","--no-reset", is_flag=True, help="Don't reboot after updating")
@click.option("-s","--source", type=click.Path(dir_okay=True,file_okay=True,path_type=anyio.Path), help="Files to sync")
@click.option("-d","--dest", type=str, default="", help="Destination path")
@click.option("-R","--root", type=str, default="/", help="Destination root")
@click.option("-S","--state", type=str, help="State to enter")
@click.option("-f","--force-exit", is_flag=True, help="Halt via an error packet")
@click.option("-e","--exit", is_flag=True, help="Halt using an exit message")
@click.option("-c","--config", type=click.File("rb"), help="Config file to copy over")
@click.option("-v","--verbose", is_flag=True, help="Use verbose mode on the target")
@click.option("-m","--mplex","--multiplex", is_flag=True, help="Run the multiplexer after syncing")
@click.option("-M","--mark", type=int, help="Serial marker", hidden=True)
@click.option("-C","--cross",help="path to mpy-cross")
async def setup(obj, source, root, dest, no_run, no_reset, force_exit, exit, verbose, state, config, mplex, cross, mark):
	"""
	Initial sync of MoaT code to a MicroPython device.

	If MoaT is already running on the target and "sync" doesn't work, 
	you can use "-e" or "-f" to stop it.
	"""
	if not obj.port:
		raise click.UsageError("You need to specify a port")
	if no_run and verbose:
		raise click.UsageError("You can't not-start the target in verbose mode")
#	if not source:
#		source = anyio.Path(__file__).parent / "_embed"

	async with get_serial(obj) as ser:

		if force_exit or exit:
			if force_exit:
				pk = b"\xc1\xc1"
			else:
				pk = msgpack.Packer().packb(dict(a=["sys","stop"],code="SysStoP"))
				pk = pk+b"\xc1"+pk

			if obj.reliable:
				from serialpacker import SerialPacker
				sp=SerialPacker(**({"mark":mark} if mark is not None else {}))
				h,pk,t = sp.frame(pk)
				pk = h+pk+t

			await ser.send(pk)
			logger.debug("Sent takedown: %r",pk)
			while True:
				m = None
				with anyio.move_on_after(0.2):
					m = await ser.receive()
					logger.debug("IN %r",m)
				if m is None:
					break

		async with DirectREPL(ser) as repl:
			dst = MoatDevPath(root).connect_repl(repl)
			if source:
				if not dest:
					dest = str(source)
					pi = dest.find("/_embed/")  
					if pi > 0:
						dest = dest[pi+8:]
						dst /= dest
				else:
					dst /= dest
				await copy_over(source, dst, cross=cross)
			if state:
				await repl.exec(f"f=open('moat.state','w'); f.write({state!r}); f.close()")
			if config:
				cfg = yload(config)
				cfg = clean_cfg(cfg)
				cfg = msgpack.Packer().pack(cfg)
				f = ABytes("moat.cfg",cfg)
				await copy_over(f, MoatDevPath("moat.cfg").connect_repl(repl), cross=cross)

			if no_reset:
				return

			await repl.soft_reset(run_main=False)
			if no_run:
				return

			o,e = await repl.exec_raw(f"from main import go_moat; go_moat(state='once',log={verbose !r})", timeout=30)
			if o:
				print(o)
			if e:
				print("ERROR", file=sys.stderr)
				print(e, file=sys.stderr)
				sys.exit(1)

		async with get_link_serial(obj, ser) as req:
			res = await req.send(["sys","test"])
			assert res == b"a\x0db\x0ac", res

			res = await req.send("ping","pong")
			if res != "R:pong":
				raise RuntimeError("wrong reply")
			print("Success:", res)

	if mplex:
		await _mplex(obj)


			
@cli.command(short_help='Sync MoaT code')
@click.pass_obj
@click.option("-s","--source", type=click.Path(dir_okay=True,file_okay=True,path_type=anyio.Path), required=True, help="Files to sync")
@click.option("-d","--dest", type=str, required=True, default="", help="Destination path")
@click.option("-C","--cross",help="path to mpy-cross")
async def sync(obj, source, dest, cross):
	"""
	Sync of MoaT code on a running MicroPython device.

	"""
	async with get_link(obj) as req:
		add_client_hooks(req)

		dst = MoatFSPath("/"+dest).connect_repl(req)
		await copy_over(source, dst, cross=cross)

			
@cli.command(short_help='Reboot MoaT node')
@click.pass_obj
@click.option("-S","--state", help="State after reboot")
async def boot(obj, state):
	"""
	Restart a MoaT node

	"""
	async with get_link(obj) as req:
		add_client_hooks(req)

		if state:
			await req.send(["sys","state"],state=state)

		# reboot via the multiplexer
		logger.info("Rebooting target.")
		await req.send(["mplex","boot"])

		#await t.send(["sys","boot"], code="SysBooT")
		await anyio.sleep(2)

		res = await req.request.send(["sys","test"])
		assert res == b"a\x0db\x0ac", res

		res = await req.request.send("ping","pong")
		if res != "R:pong":
			raise RuntimeError("wrong reply")
		print("Success:", res)

			
@cli.command(short_help='Send a MoaT command')
@click.pass_obj
@click.argument("path", nargs=1, type=P)
@attr_args(with_path=False,with_proxy=True)
async def cmd(obj, path, **attrs):
	"""
	Send a MoaT command.

	"""
	val = {}
	val = process_args(val, **attrs)
	if len(path) == 0:
		raise click.UsageError("Path cannot be empty")

	async with get_link(obj) as req:
		add_client_hooks(req)

		try:
			res = await req.send(list(path), val)
		except RemoteError as err:
			yprint(dict(e=str(err.args[0])))
		else:
			yprint(res)

@cli.command(short_help='Get / Update the configuration')
@click.pass_obj
@click.option("-C","--write-current", is_flag=True, help="Write current config to flash")
@click.option("-r","--replace", is_flag=True, help="Send our config data")
@click.option("-f","--fallback", is_flag=True, help="Change fallback config data")
@click.option("-c","--current", is_flag=True, help="Read current config data")
@attr_args(with_proxy=True)
async def cfg(obj, replace, fallback, current, write_current, **attrs):
	"""
	Update a remote configuration.

	Writing to the remote config is persistent.

	The selected config is printed if no modifiers are used.
	"""
	from copy import deepcopy
	has_attrs = any(a for a in attrs.values())

	if write_current:
		if has_attrs or fallback or replace or current:
			raise click.UsageError("Can't use 'write-current' with anything else")
		mode = 1
	elif not fallback:
		mode = 0 if current else 2
	elif current:
		raise click.UsageError("Can't use both 'fallback' and 'current'")
	else:
		mode = 3

	async with get_link(obj) as req:
		add_client_hooks(req)

		if replace:
			val = deepcopy(clean_cfg(obj.cfg))
		elif not has_attrs and not write_current:
			val = await req.send(["sys","cfg"], mode=mode)
		else:
			val = {}

		if not replace and not has_attrs and not write_current:
			yprint(val)
		else:
			val = process_args(val, **attrs)
			try:
				res = await req.send(["sys","cfg"], cfg=val, mode=mode)
			except RemoteError as err:
				yprint(dict(e=str(err.args[0])))
				sys.exit(1)
			else:
				yprint(res)

			
@cli.command(short_help='Run the multiplexer')
@click.option("-n","--no-config", is_flag=True, help="don't fetch the config from the client")
@click.option("-d","--debug", is_flag=True, help="don't retry on (some) errors")
@click.option("-r","--remote", type=str, help="talk to this system")
@click.pass_obj
async def mplex(obj, **kw):
	await _mplex(obj, **kw)

async def _mplex(obj, no_config=False, debug=None, remote=False):
	"""
	Sync of MoaT code on a running MicroPython device.

	"""
	if not obj.port:
		raise click.UsageError("You need to specify a port")
	if not obj.socket:
		raise click.UsageError("You need to specify a socket")

	@asynccontextmanager
	async def stream_factory(req):
		# build a serial stream link
		async with get_serial(obj) as ser:
			async with get_link_serial(obj, ser, request_factory=req) as link:
				yield link

	@asynccontextmanager
	async def net_factory(req):
		# build a network connection link
		async with get_remote(obj, remote, port=27587, request_factory=req) as link:
			yield link

	async def sig_handler(tg):
		import signal
		with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM, signal.SIGHUP) as signals:
			async for signum in signals:
				tg.cancel()
				break  # default handler on next

	async with TaskGroup() as tg:
		await tg.spawn(sig_handler, tg)
		obj.debug = False  # for as_service

		async with as_service(obj):
			mplex = Multiplexer(net_factory if remote else stream_factory, obj.socket, obj.cfg.micro, fatal=debug)
			await mplex.serve(load_cfg=not no_config)


@cli.command()
@click.option("-b", "--blocksize", type=int, help="Max read/write message size", default=256)
@click.argument("path", type=click.Path(file_okay=False, dir_okay=True), nargs=1)
@click.pass_obj
async def mount(obj, path, blocksize):
	"""Mount a controller's file system on the host"""
	async with get_link(obj) as req:
		add_client_hooks(req)

		import pyfuse3

		from moat.micro.fuse import Operations

		operations = Operations(req)
		if blocksize:
			operations.max_read = blocksize
			operations.max_write = blocksize

		logger.debug('Mounting...')
		fuse_options = set(pyfuse3.default_options)  # pylint: disable=I1101
		fuse_options.add('fsname=microfs')
#	   fuse_options.add(f'max_read={operations.max_read}')
		if obj.debug > 1:
			fuse_options.add('debug')
		pyfuse3.init(operations, str(path), fuse_options)  # pylint: disable=I1101

		logger.debug('Entering main loop..')
		async with anyio.create_task_group() as tg:
			try:
				tg.start_soon(pyfuse3.main)  # pylint: disable=I1101
				while True:
					await anyio.sleep(99999)

			finally:
				pyfuse3.close(  # pylint: disable=I1101  # was False but we don't continue
					unmount=True
				)
				tg.cancel_scope.cancel()

