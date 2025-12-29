(moat-lib-stream)=
# Streaming

```{include} ../../packaging/moat-lib-stream/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

See the {doc}`details` page for in-depth documentation on stream types, class
hierarchy, and usage patterns.

### Logging

Use `LogMsg`, `LogBlk`, or `LogBuf` to log all traffic through a layer:

```python
from moat.lib.stream import LogMsg

async with protocol_layer as proto:
    async with LogMsg(proto, {"txt": "MyProto"}) as logged:
        # All send/recv calls are logged
        await logged.send(msg)
```

### Console Data

Message and block layers support out-of-band console data via `cwr` and `crd`
methods for transmitting raw bytes alongside structured messages.

```{toctree}
:maxdepth: 2
:hidden:

details
api
```
