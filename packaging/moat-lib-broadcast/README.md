# Broadcasting

% start synopsis

This module provides async broadcasting, with a finite, non-blocking
message queue and data loss detection.

% end synopsis

## Installation

```bash
pip install moat-lib-broadcast
```

## Usage

```python
from moat.lib.broadcast import Broadcaster
import anyio
from contextlib import aclosing

async def reader(bc):
    async with aclosing(bc) as mq:
        async for msg in mq:
            print(f"Received: {msg}")

async with anyio.create_task_group() as tg, Broadcaster() as bc:
    # Start readers
    tg.start_soon(reader, aiter(bc))
    tg.start_soon(reader, bc.reader(10))  # explicit queue length

    # Send messages
    bc("Hello")
    await anyio.sleep(0.01)
    bc("World")
```

## License

This project is part of the MoaT ecosystem and is licensed under the same terms.
