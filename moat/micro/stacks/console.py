"""
Helper for building a MoaT stack on top of a byte stream (serial, TCP, …).
"""

from __future__ import annotations

from moat.lib.stream import BaseMsg


def console_stack(stream, cfg, cons=False):
    # lossy=False, log=False, use_console=False, msg_prefix=None
    """
    Build a message stack on top of a MoaT bytestream.

    Configuration:
        link(dict):
            Link control; see below.
        log(dict):
            If present, log high-level messages.
        log(dict):
            If present, log messages
        log_raw(dict):
            If present, log the bytestream.

    Link control:
        cbor(bool):
            must be ``True``.
        lossy(bool):
            set if the stream is not 100% reliable.
        frame(int|dict):
            control protocol framing.
            If an integer, the character that starts a packet.
            Otherwise configuration for a `SerialPacker` instance.
        console(bool):
            set if incoming non-framed data should be processed.

    If `lossy` is ``True``, `frame` must be a dict.

    There is no frame character escaping. Choose a value that cannot occur
    in an ASCII or possibly UTF-8 bytestream, i.e. ≥ 0xF8.
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
        from moat.lib.stream import LogMsg  # noqa: PLC0415

        stream = LogMsg(stream, log_raw)

    if isinstance(frame, dict):
        from moat.lib.stream import CBORMsgBlk  # noqa: PLC0415
        from moat.micro.proto._stream import SerialPackerBlkBuf  # noqa: PLC0415

        stream = SerialPackerBlkBuf(stream, frame=frame, cons=cons)
        stream = CBORMsgBlk(stream, cfg)
    else:
        from moat.lib.stream import CBORMsgBuf  # noqa: PLC0415

        stream = CBORMsgBuf(stream, dict(msg_prefix=frame, console=cons))

    assert isinstance(stream, BaseMsg)

    if lossy:
        if lossy is True:
            lossy = {}
        from moat.lib.stream import ReliableMsg  # noqa: PLC0415

        if log_rel is not None:
            from moat.lib.stream import LogMsg  # noqa: PLC0415

            stream = LogMsg(stream, log_rel)

        stream = ReliableMsg(stream, lossy)

    if log is not None:
        from moat.lib.stream import LogMsg  # noqa: PLC0415

        stream = LogMsg(stream, log)

    return stream
