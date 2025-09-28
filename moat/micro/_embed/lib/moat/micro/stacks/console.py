"""
Helper for building a MoaT stack on top of a byte stream (serial, TCP, …).
"""

from __future__ import annotations

from moat.micro.proto.stack import BaseMsg


def console_stack(stream, cfg, cons=False):
    # lossy=False, log=False, use_console=False, msg_prefix=None
    """
    Build a message stack on top of a MoaT bytestream.

    Set @lossy if the stream is not 100% reliable.
    Set @frame to control protocol framing.
    Set @console if incoming ASCII should be processed
    Set @msg_prefix to the SerialPacker (or CBOR) lead-in character.
    """

    if not hasattr(stream, "rd") or not hasattr(stream, "wr"):
        raise TypeError(f"need a BaseBuf not {stream}")

    link = cfg.get("link", {})
    cons = link.get("console", cons)
    frame = link.get("frame", None)
    lossy = link.get("lossy", None)
    log = cfg.get("log", None)
    log_raw = cfg.get("log_raw", None)
    log_rel = cfg.get("log_rel", None)

    if log_raw is not None:
        from moat.micro.proto.stack import LogMsg  # noqa: PLC0415

        stream = LogMsg(stream, log_raw)

    if link.get("cbor", False):
        raise NotImplementedError("CBOR")
    else:
        if isinstance(frame, dict):
            from moat.micro.proto.stream import CBORMsgBlk, SerialPackerBlkBuf  # noqa: PLC0415

            stream = SerialPackerBlkBuf(stream, frame=frame, cons=cons)
            stream = CBORMsgBlk(stream, cfg)
        else:
            from moat.micro.proto.stream import CBORMsgBuf  # noqa: PLC0415

            stream = CBORMsgBuf(stream, dict(msg_prefix=frame, console=cons))

    assert isinstance(stream, BaseMsg)

    if lossy:
        if lossy is True:
            lossy = {}
        from moat.micro.proto.reliable import ReliableMsg  # noqa: PLC0415

        if log_rel is not None:
            from moat.micro.proto.stack import LogMsg  # noqa: PLC0415

            stream = LogMsg(stream, log_rel)

        stream = ReliableMsg(stream, lossy)

    if log is not None:
        from moat.micro.proto.stack import LogMsg  # noqa: PLC0415

        stream = LogMsg(stream, log)

    return stream
