# Stream Infrastructure

% start synopsis
% start main

This module provides base classes for handling data streams in a structured manner.

% end synopsis

## Overview

This package implements infrastructure for building layered communication stacks:

- **BaseMsg** - Message-based communication (Python objects)
- **BaseBlk** - Block-based communication (delimited bytestrings)
- **BaseBuf** - Buffer-based communication (undelimited bytestreams)

## Layered Communication Stacks

Build communication stacks by layering protocols:

```python
from moat.lib.stream import StackedBlk

class Compression(StackedBlk):
    async def snd(self, blk):
        compressed = compress(blk)
        await self.s.send(compressed)

    async def rcv(self):
        blk = await self.s.recv()
        return decompress(blk)

# Stack layers
link = SerialLink(cfg)  # BaseBuf
link = Packetizer(link, cfg)  # StackedBlk
link = Compressor(link, cfg)  # StackedBlk
link = Codec(link, cfg)  # StackedMsg
async with link:
    await link.send({"data": "hello"})
```

% end main

## License

This project is part of the MoaT ecosystem and is licensed under the same terms.
