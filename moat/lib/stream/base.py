"""
This package implements some basic infrastructure for handling data
streams in a structured manner. It contains three distinct classes:

- `BaseMsg` transports Python objects, using `send` and `recv`.
- `BaseBlk` transports delimited bytestrings, using `snd` and `rcv`.
- `BaseBuf` transports undelimited bytestrings, using `wr` and `rd`.

Additionally, message- and block-based classes understand `cwr` and `crd`
which transport out-of-band data. Typically these contain raw console bytes
that are interleaved with structured data; they are used on channels which
needs to multiplex both.

The common theme for using these classes is

- You assemble a communication stack bottom-up: start with a serial link;
  add packetizing, retransmission, and an object-codec.
- Using the top level as an async context managers establishes the complete
  stack; leaving the context tears it down.
- Most likely, connect the result to a [Base]MsgHandler.

Everything is fully asynchronous. There is no "new incoming data" callback:
it's the upper layer's job to repeatedly call the appropriate method to
read or receive new messages.

A `wrap` method provides a secondary context that can be used for
a persistent outer context, e.g. to keep a listening socket open.

Use :py:func:`build_stack` to assemble a stack from a configuration
dictionary.  The function is flexible: it can auto-detect the required
layers from the standard ``link`` / ``log`` / ``log_raw`` / ``log_rel``
keys, or you can pass an explicit ``layers`` list for full control.
"""

from __future__ import annotations

from moat.util import attrdict
from moat.lib.micro import ACM, AC_exit, AC_use

from collections.abc import Mapping

# Typing

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from typing import Any, Self

    Buffer = bytes | bytearray | memoryview
    MutBuffer = bytearray | memoryview
    _AACMBase = AbstractAsyncContextManager
else:
    Buffer = bytes
    MutBuffer = bytearray
    _AACMBase = object


class _NullCtx:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *tb):
        pass


_nullctx = _NullCtx()


class Base(_AACMBase):
    """
    The MoaT stream base class for "something connected".

    This class *must* be used as an async context manager.

    Usage:

    Use the :py:func:`moat.lib.micro.AC_use` helper if you need
    to call an async context manager or to register a destructor.

    Augment `setup` or `teardown` to add non-stream related features.

    Override `wrap` to contain an async context manager that holds resources
    which must survive reconnection, e.g. a MQTT link's persistent state or
    a listening socket.
    """

    s = None
    cfg: attrdict

    def __init__(self, cfg: attrdict | None = None):
        if cfg is None:
            cfg = attrdict()
        self.cfg = cfg

    @property
    def cfg_name(self):
        "Some name to disambiguate this part"
        try:
            return self.cfg.name
        except AttributeError:
            return self.__class__.__name__

    def wrap(self) -> AbstractAsyncContextManager:
        """
        Async context manager for holding a cross-connection context.

        By default does nothing.
        """
        return _nullctx

    async def __aenter__(self) -> Self:
        res = self
        AC = ACM(self)
        await AC(self.teardown)
        try:
            await self.setup()
            if (ctx := getattr(self, "_ctx", None)) is not None:
                res = await AC(ctx())
            return res
        except BaseException as exc:
            await AC_exit(self, type(exc), exc, getattr(exc, "__traceback__", None))
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return await AC_exit(self, exc_type, exc, tb)

    async def setup(self):
        """
        Basic async setup method. You may use AC_exit.

        Call the superclass first, when overriding.
        """

    async def teardown(self):
        """
        Object destructor.

        Should not fail when called with a partially-created object.
        """


class BaseConn(Base):
    """
    This is the MoaT stream base class for "something connected that talks".

    This class *must* be used as an async context manager.

    Usage:

    Override :py:meth:`BaseConn.stream` to create the data link.
    Use :py:func:`moat.lib.micro.AC_use` to
    call an async context manager or to register a destructor.

    Augment `setup` or `teardown` to add non-stream related features.
    """

    s: Any = None

    async def setup(self):
        """
        Object construction.

        By default, assigns the result of calling :py:meth:`BaseConn.stream` to the attribute
        ``s``.
        """
        if self.s is not None:
            raise RuntimeError("Busy!")

        self.s = await self.stream()

    async def teardown(self):
        """
        Object destructor.

        Should not fail when called with a partially-created object.
        """
        self.s = None

    async def stream(self):
        """
        Data stream setup.

        You need to use `moat.lib.micro.AC_use` for setting up an async context
        or to register a cleanup handler.
        """
        raise NotImplementedError(f"'stream' in {self!r}")


class BaseMsg(BaseConn):
    """
    A stream base module for messages. May not be useful.

    Implement send/recv.
    """

    async def send(self, m: Any) -> Any:
        """
        Send a message.
        """
        raise NotImplementedError(f"'send' in {self!r}")

    async def recv(self) -> Any:
        """
        Receive a message.
        """
        raise NotImplementedError(f"'recv' in {self!r}")


class BaseBlk(BaseConn):
    """
    A stream base module for bytestrings. May not be useful.

    Implement snd/rcv.
    """

    async def snd(self, m: Buffer | bytes) -> None:
        """
        Send a block of bytes.
        """
        raise NotImplementedError(f"'send' in {self!r}")

    async def rcv(self) -> Buffer | bytes:
        """
        Receive a block of bytes.
        """
        raise NotImplementedError(f"'recv' in {self!r}")


class BaseBuf(BaseConn):
    """
    A stream base module for bytestreams.

    Implement rd/wr.
    """

    async def rd(self, buf: MutBuffer) -> int:
        """
        Read some bytes.

        @buf is a bytearray to read data into. The return value is the
        number of bytes filled.

        This method never returns zero. End-of-file raises `EOFError`.
        """
        raise NotImplementedError(f"'rd' in {self!r}")

    async def wr(self, data: Buffer) -> int:
        """
        Write some bytes.
        """
        raise NotImplementedError(f"'wr' in {self!r}")


class StackedConn(BaseConn):
    """
    Base class for connection stacking.

    Connection stacks have a lower layer. Our `stream` methods uses it as an
    async context manager to create connection from it, using its

    Args:
        link(BaseConn): The lower layer to run on top of.
        cfg: Config data
    """

    link: BaseConn | None = None

    def __init__(self, link: BaseConn, cfg):
        super().__init__(cfg=cfg)
        self.link = link

    def wrap(self):  # noqa:D102
        if self.link is None:
            raise RuntimeError("No link")
        return self.link.wrap()

    async def stream(self) -> BaseConn:
        """
        Generate the low-level connection this module uses.

        By default, returns the linked stream's async context.
        """
        if self.link is None:
            raise RuntimeError("No link")
        return await AC_use(self, self.link)


class StackedMsg(StackedConn, BaseMsg):
    """
    A no-op stack module for messages. Override to implement interesting features.

    Use the attribute "s" to store the linked stream's context.

    Args:
        link(BaseMsg): The lower layer to run on top of.
        cfg: Config data
    """

    async def send(self, m: Any) -> Any:
        "Send. Transmits a structured message"
        return await self.s.send(m)

    async def recv(self) -> Any:
        "Receive. Returns a message."
        return await self.s.recv()

    async def cwr(self, buf: Buffer) -> None:
        "Console Send. Returns when the buffer is transmitted."
        await self.s.cwr(buf)

    async def crd(self, buf: MutBuffer) -> int:
        "Console Receive. Returns data by reading into a buffer."
        return await self.s.crd(buf)


class StackedBuf(StackedConn, BaseBuf):
    """
    A no-op stack module for byte steams. Override to implement interesting features.

    Use the attribute "s" to store the linked stream's context.

    Args:
        link(BaseBuf): The lower layer to run on top of.
        cfg: Config data
    """

    async def wr(self, data: Buffer) -> int:
        "Send. Returns when the buffer is transmitted."
        return await self.s.wr(data)

    async def rd(self, buf: MutBuffer) -> int:
        "Receive. Returns data by reading into a buffer."
        return await self.s.rd(buf)


class StackedBlk(StackedConn, BaseBlk):
    """
    A no-op stack module for bytestrings. Override to implement interesting features.

    Use the attribute "s" to store the linked stream's context.

    Args:
        link(BaseBlk): The lower layer to run on top of.
        cfg: Config data
    """

    cwr = StackedMsg.cwr
    crd = StackedMsg.crd

    async def snd(self, m: Buffer | bytes) -> None:
        "Send. Transmits a structured message"
        await self.s.snd(m)

    async def rcv(self) -> Buffer | bytes:
        "Receive. Returns a message."
        return await self.s.rcv()


# ---------------------------------------------------------------------------
# Stack builder
# ---------------------------------------------------------------------------

# Registry of known layer factories.  Each entry maps a name to a callable
# ``(stream, cfg) -> stream``.  The callable receives the current bottom
# stream and the *full* config dict; it returns the new (wrapped) stream.
#
# Factories are registered lazily to avoid importing heavy modules (CBOR,
# Reliable, SerialPacker, …) at module load time.  Use :func:`_layer` to
# look up a factory by name.
_LAYER_FACTORIES: dict[str, str] = {
    # name -> dotted module path containing the factory function
    # The factory function itself must have the same name as the layer.
}


def _register_layer(name: str, module: str) -> None:
    """Register a layer factory.

    Args:
        name: Layer name used in config ``layers`` lists.
        module: Dotted module path that contains a same-named factory
            callable ``(stream, cfg) -> stream``.
    """
    _LAYER_FACTORIES[name] = module


def _layer_factory(name: str):
    """Resolve a layer factory by name, importing its module on demand."""
    try:
        module = _LAYER_FACTORIES[name]
    except KeyError:
        raise ValueError(f"Unknown stream layer: {name!r}") from None
    mod = __import__(module, globals(), None, (name,))
    return getattr(mod, name)


def build_stack(stream, cfg: attrdict, *, framed: bool | None = None, cons: bool = False):
    """Build a message stack on top of a MoaT bytestream.

    This is the central, flexible stack assembler.  It replaces the
    older per-transport ``serial_stack`` / ``ws_stack`` helpers (which
    now delegate here).

    Two modes of operation:

    Explicit layers
        If ``cfg["layers"]`` is a list, each element describes one layer
        to add.  Elements may be:

        * a string — name of a registered layer factory
          (e.g. ``"cbor_blk"``, ``"reliable"``, ``"log"``);
        * a dict with keys ``name`` (required) and ``cfg`` (optional,
          defaults to an empty dict) — the sub-dict is passed to the
          layer factory instead of the global config.

        Layers are applied bottom-up: the first element wraps *stream*
        directly, the second wraps the result, and so on.

    Implicit (auto-detect)
        When ``cfg["layers"]`` is absent, the layers are inferred from
        the standard config keys:

        ``log_raw``
            If present, a raw-byte logging layer is added at the very
            bottom.
        ``link.frame`` / ``framed``
            Select the codec layer.  Three cases:

            * ``framed=True`` — the bottom stream already carries message
              boundaries (a block stream, e.g. a websocket); it is wrapped
              with ``cbor_blk`` directly, no framing.
            * ``framed=False`` — force the self-delimiting codec
              (``cbor_buf``).
            * ``framed=None`` (default) — auto-detect from ``link.frame``:
              a mapping selects HDLC framing (``serial_frame``) followed by
              ``cbor_blk`` (the bottom is a byte stream needing framing);
              an int or absence selects the self-delimiting codec
              (``cbor_buf``, with the int as the message prefix byte).
        ``link.lossy``
            If truthy, a :class:`~moat.lib.stream.reliable.ReliableMsg`
            layer is inserted.  An optional ``log_rel`` log layer is
            added just below it.
        ``log``
            If present, a high-level message logging layer is added on
            top.

    Args:
        stream: The bottom-layer stream (``BaseBuf`` or ``BaseBlk``).
        cfg: Configuration dictionary.  See above.
        framed: Select the codec in implicit mode — ``True`` for a
            block-delimited bottom (block codec, no framing), ``False``
            to force the self-delimiting codec, ``None`` to auto-detect
            from ``link.frame``.
        cons: Console flag forwarded to the framing/codec layers in
            implicit mode.

    Returns:
        The top of the assembled stack (a :class:`BaseMsg`).
    """
    layers = cfg.get("layers", None)

    if layers is not None:
        # Explicit mode: process the user-supplied layer list.
        for layer in layers:
            if isinstance(layer, str):
                name = layer
                lcfg = cfg
            else:
                name = layer["name"]
                lcfg = layer.get("cfg", cfg)
            factory = _layer_factory(name)
            stream = factory(stream, lcfg)
        return stream

    # Implicit mode: auto-detect layers from standard config keys.
    link = cfg.get("link", {})
    if cons is False:
        cons = link.get("console", False)
    frame = link.get("frame", None)
    lossy = link.get("lossy", None)
    log = cfg.get("log", None)
    log_raw = cfg.get("log_raw", None)
    log_rel = cfg.get("log_rel", None)

    # Raw byte logging at the very bottom.
    if log_raw is not None:
        stream = _layer_factory("log_raw")(stream, log_raw)

    # Codec layer: convert bytes ↔ messages.
    if framed is False:
        stream = _layer_factory("cbor_buf")(stream, cfg, frame=frame, cons=cons)
    elif framed is True:
        # Bottom already carries message boundaries (e.g. a websocket);
        # use the block codec directly, no framing.
        stream = _layer_factory("cbor_blk")(stream, cfg)
    elif isinstance(frame, Mapping):
        # Bottom is a byte stream needing HDLC framing: frame first
        # (bytes → blocks), then encode blocks as messages.
        stream = _layer_factory("serial_frame")(stream, cfg, frame=frame, cons=cons)
        stream = _layer_factory("cbor_blk")(stream, cfg)
    else:
        stream = _layer_factory("cbor_buf")(stream, cfg, frame=frame, cons=cons)

    # Reliability layer (optional).
    if lossy:
        if lossy is True:
            lossy = {}
        if log_rel is not None:
            stream = _layer_factory("log_msg")(stream, log_rel)
        stream = _layer_factory("reliable")(stream, lossy)

    # High-level message logging on top.
    if log is not None:
        stream = _layer_factory("log_msg")(stream, log)

    return stream
