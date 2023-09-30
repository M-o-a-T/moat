from moat.micro.proto.stream import AIOBuf

class UnixLink(AIOBuf):
    def __init__(self, port:str|Path):
        self.port = port

    @asynccontextmanager
    async def _ctx(self):
        raise NotImplementedError("UnixSocket on MicroPy")
        yield None

