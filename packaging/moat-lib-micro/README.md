# moat-lib-micro

% start main
% start synopsis

Compatibility wrappers for async code that runs run on both CPython/anyio
and MicroPython/asyncio.

% end synopsis

This module provides a unified interface for asynchronous programming that
works across both CPython (using anyio) and MicroPython (using asyncio).
It includes wrappers for logging and timing, common async primitives like
Event, Lock, Queue, or TaskGroup, async context managers, and more.

## Usage

The module provides consistent imports that work on both platforms:

```python
from moat.lib.micro import Event, Lock, Queue, TaskGroup, sleep

# Use these primitives the same way on both CPython and MicroPython

async def worker(evt):
    await evt.wait()

async def example():
    event = Event()
    async with TaskGroup() as tg:
        tg.start_soon(worker, event)
        await sleep(1)
        event.set()
```

% end main

## License

Licensed under the MIT License.
