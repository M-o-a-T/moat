import sys

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.

from ..cmd import Request

import logging
logger = logging.getLogger(__name__)

async def console_stack(stream=sys.stdin.buffer, s2=None, reliable=False, log=False, log_bottom=False, console=False, force_write=False, request_factory=Request):
    # Set s2 for a separate write stream.
    #
    # Set force_write if select-for-write doesn't work on your stream.
    # 
    # set @reliable if your console already guarantees lossless
    # transmission (e.g. via USB).

    if log or log_bottom:
        from ..proto import Logger
    if hasattr(stream,"aclose"):
        assert s2 is None
        assert not force_write
        s = stream
    else:
        from ..proto.stream import AsyncStream
        s = AsyncStream(stream, s2, force_write)

    cons_h = None
    if console:
        c_b = bytearray()
        def cons_h(b):
            nonlocal c_b
            if b == 10:
                logger.info("C:%s", c_b.decode("utf-8","backslashreplace"))
                c_b = bytearray()
            elif b != 13:
                if 0 <= b <= 255:
                    c_b.append(b)
                else:
                    print("Spurious:",b)

    if reliable:
        from ..proto.stream import MsgpackStream
        t = b = MsgpackStream(s, console=console, console_handler=cons_h)
    else:
        from ..proto.stream import MsgpackHandler, SerialPackerStream

        t = b = SerialPackerStream(s, console=console, console_handler=cons_h)
        t = t.stack(MsgpackHandler)

        if log_bottom:
            t = t.stack(Logger, txt="Rel")
        from ..proto.reliable import Reliable
        t = t.stack(Reliable)
    if log:
        t = t.stack(Logger, txt="Msg" if log is True else log)
    t = t.stack(request_factory)
    return t,b


