from moat.micro.proto.stream import AnyioBuf

class Link(AnyioBuf):
    def __init__(self, port:str|Path):
        self.port = port

    @asynccontextmanager
    async def _ctx(self):
        async with await anyio.connect_unix(self.port) as self.s:
            yield self

