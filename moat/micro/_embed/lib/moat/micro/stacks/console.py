import sys

from ..cmd import Request

# All Stacks builders return a (top,bot) tuple.
# The top is the Request object. You're expected to attach your Base
# (or a subclass) to it, then call `bot.run()`.


async def console_stack(
    stream,
    lossy=False,
    log=False,
    log_bottom=False,
    msg_prefix=None,
    request_factory=Request,
    ready=None,
    use_console=False,
    cfg=None,
):
    """
    Build a message stack on top of this (asyncio) stream.

    Set @lossy if the stream is not 100% reliable.
    Set @use_console if incoming ASCII should be reported.
    Set @msg_prefix to whatever serial or msgpack lead-in character.
    """

    if log or log_bottom:
        from ..proto.stack import Logger
    assert hasattr(stream, "recv")
    assert hasattr(stream, "aclose")

    cons_h = None
    if use_console:
        c_b = bytearray()

        def cons_h(b):
            nonlocal c_b
            if b == 10:
                try:
                    print("C:", c_b.decode("utf-8", "backslashreplace"), file=sys.stderr)
                except UnicodeError:
                    print("C:", c_b, file=sys.stderr)
                c_b = bytearray()
            elif b != 13:
                if 0 <= b < 128:
                    c_b.append(b)
                else:
                    print("CS:", b, file=sys.stderr)

    if lossy:
        from ..proto.stream import MsgpackHandler, SerialPackerStream

        if use_console and msg_prefix is None:
            raise RuntimeError("Lossy + console requires a prefix byte")

        t = b = SerialPackerStream(stream, msg_prefix=msg_prefix, console_handler=cons_h)
        t = t.stack(MsgpackHandler)

        if log_bottom:
            t = t.stack(Logger, txt="Rel")
        from ..proto.reliable import Reliable

        t = t.stack(Reliable)
    else:
        from ..proto.stream import MsgpackStream

        t = b = MsgpackStream(stream, msg_prefix=msg_prefix, console_handler=cons_h)

    if log:
        t = t.stack(Logger, txt="Msg" if log is True else log)
    t = t.stack(request_factory, ready=ready)
    return t, b
