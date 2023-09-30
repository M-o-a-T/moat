from moat.micro.proto.stream import AnyioBuf

class UnixLink(AnyioBuf):
    def __init__(self, port:str|Path):
        self.port = port

    @asynccontextmanager
    async def _ctx(self):
        async with await connect_unix(self.port) as self.s:
            yield self

        await client.send(b'Client\n')
        response = await client.receive(1024)
        raise NotImplementedError

