import sys

def console_stack(stream, cfg, cons=False):
    # lossy=False, log=False, use_console=False, msg_prefix=None
    """
    Build a message stack on top of a MoaT bytestream.

    Set @lossy if the stream is not 100% reliable.
    Set @frame to control protocol framing.
    Set @console if incoming ASCII should be 
    Set @msg_prefix to the SerialPacker (or msgpack) lead-in character.
    """

    assert hasattr(stream, "recv")
    assert hasattr(stream, "aclose")

    cons = cfg.get("console", cons)
    frame = cfg.get("frame", None)
    lossy = cfg.get("lossy", None)
    log = cfg.get("log", None)

    assert isinstance(stream, BaseBuf)

    if cfg.get("cbor", False):
        raise NotImplementedError("CBOR")
    else:
        if isinstance(frame, dict):
            from ..proto.stream import SerialPackerBlkBuf
            stream = SerialPackerBlkBuf(stream, frame=frame, cons=cons)
            stream = MsgpackMsgBlk(stream)
        else:
            from ..proto.stream import MsgpackHandler
            stream = MsgpackMsgBuf(stream, msg_prefix=frame)

    assert isinstance(stream, BaseMsg)

    if lossy:
        from ..proto.reliable import ReliableMsg

        stream = ReliableMsg(stream, **lossy)

    if log:
        from ..proto.stack import Logger
        stream = Logger(stream)

    return stream
