"""Layer factory functions for :py:func:`~moat.lib.stream.build_stack`.

Each factory has the signature ``(stream, cfg[, **kw]) -> stream`` and
wraps *stream* with one layer of the stack.  The factories are registered
in :py:mod:`moat.lib.stream` at import time so that ``build_stack`` can
resolve them by name.
"""

from __future__ import annotations

from moat.lib.stream.base import _register_layer

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from moat.util import attrdict
    from moat.lib.stream import BaseBuf, BaseMsg


def cbor_buf(stream: BaseBuf, cfg: attrdict, *, frame=None, cons: bool = False) -> BaseMsg:  # noqa: ARG001
    """Self-delimiting CBOR codec layer.

    Wraps a byte stream with :class:`~moat.lib.stream.CBORMsgBuf`,
    which assumes the transport is reliable but does not preserve
    message boundaries.

    Args:
        stream: The bottom-layer byte stream.
        cfg: Full config dict (used for codec selection).
        frame: Prefix byte for messages (``msg_prefix``).  Should be
            an integer or ``None``; a dict is ignored (use
            :func:`cbor_blk` for framed mode).
        cons: Console multiplexing flag.
    """
    from moat.lib.stream import CBORMsgBuf  # noqa: PLC0415

    if isinstance(frame, dict):
        frame = None
    return CBORMsgBuf(stream, dict(msg_prefix=frame, console=cons))


def cbor_blk(stream, cfg: attrdict, **kw) -> BaseMsg:  # noqa: ARG001
    """Block-CBOR codec layer.

    Wraps a **block** stream (one carrying message boundaries via
    ``snd``/``rcv``, e.g. a websocket) with
    :class:`~moat.lib.stream.CBORMsgBlk`.

    This layer takes blocks and turns them into messages; it does not frame.
    To feed it a raw byte stream, add the framing layer
    (:func:`serial_frame`) first, or use :func:`cbor_buf` for the
    self-delimiting path. Keyword arguments are accepted and ignored for
    backwards compatibility with older callers.

    Args:
        stream: A block-oriented stream (``snd``/``rcv``).
        cfg: Full config dict (used for codec selection).
    """
    from moat.lib.stream import CBORMsgBlk  # noqa: PLC0415

    return CBORMsgBlk(stream, cfg)


def serial_frame(
    stream,
    cfg: attrdict,  # noqa: ARG001
    *,
    frame: dict | None = None,
    cons: bool | int = False,
):
    """HDLC-like framing layer (bytes \u2192 blocks).

    Wraps a **byte** stream (``rd``/``wr``) with
    :class:`~moat.lib.stream.SerialPackerBlkBuf`, producing a block stream
    suitable as input to :func:`cbor_blk`.

    Args:
        stream: A byte-oriented stream (``rd``/``wr``).
        frame: SerialPacker configuration dict.
        cons: Console multiplexing flag.
    """
    from moat.lib.stream.serial import SerialPackerBlkBuf  # noqa: PLC0415

    if frame is None:
        frame = {}
    return SerialPackerBlkBuf(stream, frame=frame, console=cons)


def reliable(stream, cfg: attrdict) -> BaseMsg:
    """Reliability / retransmission layer.

    Wraps a message stream with :class:`~moat.lib.stream.ReliableMsg`.

    Args:
        stream: The message stream to protect.
        cfg: Configuration for the ReliableMsg layer (window, timeout, …).
    """
    from moat.lib.stream import ReliableMsg  # noqa: PLC0415

    return ReliableMsg(stream, cfg)


def log_msg(stream, cfg: attrdict) -> BaseMsg:
    """Message-level logging layer.

    Wraps a stream with :class:`~moat.lib.stream.LogMsg`.

    Args:
        stream: The stream to log.
        cfg: Logging configuration (``txt``, ``decode``, …).
    """
    from moat.lib.stream import LogMsg  # noqa: PLC0415

    return LogMsg(stream, cfg)


def log_raw(stream, cfg: attrdict):
    """Raw byte-level logging layer.

    Same as :func:`log_msg` but conceptually placed at the bottom of the
    stack to log raw bytes.  Uses :class:`~moat.lib.stream.LogMsg` /
    :class:`~moat.lib.stream.LogBlk` depending on the stream type.

    Args:
        stream: The byte/block stream to log.
        cfg: Logging configuration.
    """
    from moat.lib.stream import LogMsg  # noqa: PLC0415

    return LogMsg(stream, cfg)


# Alias: "log" is the common shorthand for the message-level log layer.
log = log_msg


# Register all factories with the build_stack resolver.
_register_layer("cbor_buf", "moat.lib.stream._layers")
_register_layer("cbor_blk", "moat.lib.stream._layers")
_register_layer("serial_frame", "moat.lib.stream._layers")
_register_layer("reliable", "moat.lib.stream._layers")
_register_layer("log_msg", "moat.lib.stream._layers")
_register_layer("log_raw", "moat.lib.stream._layers")
_register_layer("log", "moat.lib.stream._layers")
