# Async code on MoaT-Micro

When you MoaT-ify a microcontroller, code that runs an asyncio mainloop
is installed and (usually) auto-started.

This means that any code you write must also be async compatible.


## Compatibility with CPython

MoaT on CPython does not use asyncio directly. It uses `anyio`, which runs
on top of either asyncio or Trio.

MoaT supplies compatibility code in the `moat.util.compat` module which
masks the difference and allows you to code in a consistent style, avoiding
several of asyncio's historic anti-patterns.

As the MoaT link is transparent, you can thus write and debug your
application code on the host, using standard CPython, then copy it to the
satellite(s).


### async conventions

Asyncio deals with coroutines, mainly for historical reasons: you write
code like `asyncio.run(async_fn(42))` (or `create_task(…)`). This however
is an anti-pattern, because `async_fn` is called immediately, before the
async runtime or the task is even set up; it just returns a coroutine
that's deferred.

The Trio/AnyIO convention, which MoaT mirrors, is to be explicit:
`anyio.run(async_fn, 42)`. `async_fn` is now called after the async loop
is set up or the task is created, i.e. in the correct context. This matters
e.g. when you use a sync function/method wrapper.


## The MoaT console

MoaT-Micro exports the MicroPython REPL to the MoaT link.

Behind the scenes, this works by starting the async main loop
as usual. However, instead of staying in the loop until MoaT ends,
a special handler is attached to the REPL (via `os.dupterm`).

The loop exits when setup is complete, and re-entered when MicroPython
tries to read from standard input.

Thus you can interact with your microcontroller while copying files to it
and without interrupting its normal background processing.


### Running sync procedures and methods

If they finish within a couple of milliseconds: No problem.

If they don't, the system will stall, possibly disrupting
your background processing. Also, if you have configured a watchdog,
after a few seconds your controller will reboot rather abruptly.

You cannot interrupt a sync command because data input relies on a
running async loop, and that doesn't happen

#### ... in a thread

`moat.util.compat` exports a `to_thread` function which, as the name
implies, runs the given code in the background as a separate thread.

`to_thread` itself is async; see below on how to call async functions
from the command line.


### Async procedures and methods

To run (and return the result of) an async function, use `moat.call`:

	import moat
	from moat.util.compat import sleep_ms
	async def twice(n):
	    await sleep_ms(50*n)
		return 2*n
	print(moat.call(twice, 21))

	42

Control-C will interrupt this.


#### Running in the background

MoaT-Micro can do this, too:

	job = moat.bg(twice, 1234)
	...
	moat.call(job.get)
	# or: moat.call(job.wait)
	#     job.value.unpack()

	2468

You can stop background tasks with `cancel`. Any exceptions raised by your job
will be re-raised when `get` or `unwrap` are called.
