from moat.micro.proto.stream import AnyioBuf

class Link(AnyioBuf):
    def __init__(self, host:str, port:int):
        self.host = host
        self.port = port

    @asynccontextmanager
    async def _ctx(self):
        async with await anyio.connect_tcp(self.host, self.port) as self.s:
            yield self

