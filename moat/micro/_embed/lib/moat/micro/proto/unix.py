from moat.micro.proto.stream import AIOBuf

class UnixLink(AIOBuf):
    def __init__(self, port:str|Path):
        self.port = port

    async def setup(self):
        raise NotImplementedError("UnixSocket on MicroPy")

