#!/usr/bin/env python3

import os
import sys

if os.path.exists("micro/lib"):
	sys.path.insert(0,"../..")
	sys.path.insert(0,".")

import msgpack
import importlib

import anyio
import asyncclick as click
from contextlib import asynccontextmanager

from moat.direct import DirectREPL
from moat.path import MoatDevPath, MoatFSPath
from moat.compat import TaskGroup
from moat.util import attrdict, as_service, P, attr_args, process_args, yprint, yload
from moat.proto.multiplex import Multiplexer
from moat.proto import RemoteError
from moat.main import ABytes, NoPort, copy_over, add_client_hooks
from moat.main import get_serial, get_link, get_link_serial, main

import logging
logger = logging.getLogger(__name__)


def clean_cfg(cfg):
	# cfg = attrdict(apps=cfg["apps"])  # drop all the other stuff
	return cfg

@main.command(short_help='Copy MoaT to MicroPython')
@click.pass_obj
@click.option("-n","--no-run", is_flag=True, help="Don't run MoaT after updating")
@click.option("-N","--no-reset", is_flag=True, help="Don't reboot after updating")
@click.option("-s","--source", type=click.Path(dir_okay=True,file_okay=True,path_type=anyio.Path), help="Files to sync")
@click.option("-d","--dest", type=str, required=True, default="", help="Destination path")
@click.option("-S","--state", type=str, help="State to enter")
@click.option("-f","--force-exit", is_flag=True, help="Halt via an error packet")
@click.option("-e","--exit", is_flag=True, help="Halt using an exit message")
@click.option("-c","--config", type=click.File("rb"), help="Config file to copy over")
@click.option("-v","--verbose", is_flag=True, help="Use verbose mode on the target")
@click.option("-m","--mplex","--multiplex", is_flag=True, help="Run the multiplexer after syncing")
@click.option("-M","--mark", type=int, help="Serial marker", hidden=True)
@click.option("-C","--cross",help="path to mpy-cross")
async def setup(obj, source, dest, no_run, no_reset, force_exit, exit, verbose, state, config, mplex, cross, mark):
	"""
	Initial sync of MoaT code to a MicroPython device.

	If MoaT is already running on the target and "sync" doesn't work, 
	you can use "-e" or "-f" to stop it.
	"""
	if not obj.port:
		raise click.UsageError("You need to specify a port")
	if no_run and verbose:
		raise click.UsageError("You can't not-start the target in verbose mode")

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
			dst = MoatDevPath("/"+dest).connect_repl(repl)
			if source:
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

			o,e = await repl.exec_raw(f"import main; main.go_moat(state='once',log={verbose !r})", timeout=30)
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


			
@main.command(short_help='Sync MoaT code')
@click.pass_obj
@click.option("-s","--source", type=click.Path(dir_okay=True,file_okay=True,path_type=anyio.Path), required=True, help="Files to sync")
@click.option("-d","--dest", type=str, required=True, default="", help="Destination path")
@click.option("-c","--cross",help="path to mpy-cross")
async def sync(obj, source, dest, cross):
	"""
	Sync of MoaT code on a running MicroPython device.

	"""
	async with get_link(obj) as req:
		add_client_hooks(req)

		dst = MoatFSPath("/"+dest).connect_repl(req)
		await copy_over(source, dst, cross=cross)

			
@main.command(short_help='Reboot MoaT node')
@click.pass_obj
@click.option("-s","--state", help="State for the next run")
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

			
@main.command(short_help='Send a MoaT command')
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

@main.command(short_help='Get / Update the configuration')
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
		elif write_current or current or not has_attrs:
			val = await req.send(["sys","cfg"], mode=mode)
		else:
			val = {}

		if not replace and not has_attrs:
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

			
@main.command(short_help='Run the multiplexer')
@click.option("-n","--no-config", is_flag=True, help="don't fetch the config from the client")
@click.option("-d","--debug", is_flag=True, help="don't retry on (some) errors")
@click.pass_obj
async def mplex(obj, no_config, debug):
	await _mplex(obj, no_config=no_config, debug=debug)

async def _mplex(obj, no_config=False, debug=None):
	"""
	Sync of MoaT code on a running MicroPython device.

	"""
	if not obj.port:
		raise click.UsageError("You need to specify a port")
	if not obj.socket:
		raise click.UsageError("You need to specify a socket")

	@asynccontextmanager
	async def stream_factory(req):
		async with get_serial(obj) as ser:
			async with get_link_serial(obj, ser, request_factory=req) as link:
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
			mplex = Multiplexer(stream_factory, obj.socket, obj.cfg, fatal=debug)
			await mplex.serve(load_cfg=not no_config)


if __name__ == "__main__":
	try:
		main(_anyio_backend="trio")
	except NoPort:
		print("No port given, socket doesn't work")
		sys.exit(1)

