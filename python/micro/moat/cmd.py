import uasyncio       
from serialpacker import SerialPacker
from msgpack import packb,unpackb
import sys

class CmdHandler:         
    # reads commands from an asyncio stream
    def __init__(self, stream, evt=None):
        self.s = stream
        self.p = SerialPacker()
        self.evt = evt

    async def process(self, msg):
        print("MSG IN", msg)

    async def run(self):
        buf = bytearray()
        while True:
            c = await self.s.read(1)
            if not c:
                raise EOFError
            msg = self.p.feed(c[0])
            if msg is None:
                b = self.p.read()
                if not b:
                    continue
                if b[0] in (3,4):
                    if self.evt is not None:
                        self.evt.set()
                    continue
                if b[0] != 0x0A:
                    buf.extend(b)
                elif buf:
                    try:
                        print(eval(buf.decode("utf-8")))
                    except Exception as exc:
                        sys.print_exception(exc)
                    buf = bytearray()
            else:
                try:
                    msg = unpackb(msg)
                except Exception as exc:
                    print("UNPACK",exc,msg)
                else:
                    self.process(msg)

    async def send(self, msg):
        msg = packb(msg)
        h,t = self.p.frame(msg)
        await self.s.write(h+msg+t)

    from serialpacker import SerialPacker
    S = SerialPacker()

