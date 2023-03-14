import sys

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.

from ..cmd import Request

async def console_stack(stream, reliable=False, log=False, log_bottom=False, msg_prefix=None, request_factory=Request, ready=None):
    # set @reliable if your console already guarantees lossless
    # transmission (e.g. via USB).

    if log or log_bottom:
        from ..proto.stack import Logger
    assert hasattr(stream,"recv")
    assert hasattr(stream,"aclose")

    cons_h = None
    if msg_prefix:
        c_b = bytearray()
        def cons_h(b):
            nonlocal c_b
            if b == 10:
                try:
                    print("C:", c_b.decode("utf-8","backslashreplace"), file=sys.stderr)
                except UnicodeError:
                    print("C:", c_b, file=sys.stderr)
                c_b = bytearray()
            elif b != 13:
                if 0 <= b < 128:
                    c_b.append(b)
                else:
                    print("CS:",b, file=sys.stderr)

    if reliable:
        from ..proto.stream import MsgpackStream
        t = b = MsgpackStream(stream, msg_prefix=msg_prefix, console_handler=cons_h)
        await b.init()
    else:
        from ..proto.stream import MsgpackHandler, SerialPackerStream

        t = b = SerialPackerStream(stream, msg_prefix=msg_prefix, console_handler=cons_h)
        t = t.stack(MsgpackHandler)

        if log_bottom:
            t = t.stack(Logger, txt="Rel")
        from ..proto.reliable import Reliable
        t = t.stack(Reliable)
    if log:
        t = t.stack(Logger, txt="Msg" if log is True else log)
    t = t.stack(request_factory, ready=ready)
    return t,b


