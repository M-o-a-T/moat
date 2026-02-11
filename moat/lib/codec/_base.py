from __future__ import annotations

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, Self

    ByteType = bytes | bytearray | memoryview
    VarByteType = bytearray | memoryview


class NoCodecError(ValueError):
    "No codec found"


class IncompleteData(ValueError):
    "Stream chopped off"


class Codec:
    """
    This is an abstract base class. It supports block and
    incremental decoders.

    To support block decoding, override the decode method.

    Incremental codecs need to support interleaved operation. This means
    that the decoder must support two modes.

    The initial mode is to append all data passed in via `feed` to an
    internal buffer. If necessary, the application then uses `unfeed` to
    read data off the start of the buffer until a packet header is
    detected.

    After the header is consumed, the application must repeat calling
    ``__anext__`` until an object is returned. (If the decoder
    raises `StopAsyncIteration`, feed more data to it and repeat.)

    The decoder must leave all incoming data extending past the object in
    its buffer. It must not attempt to decode them until the next call to
    ``__anext__``.
    """

    def __init__(self, ext=None):
        if ext is None:
            ext = Extension()  # empty
        self.ext = ext
        self.buf = b""

    def copy(self) -> Self:
        """
        Returns a new codec with identical configuration.
        """
        raise NotImplementedError

    def encode(self, obj: Any) -> ByteType:
        """
        Encode a data structure, yielding some bytes which may or may not
        be self-terminating.
        """
        raise NotImplementedError

    def decode(self, data: ByteType) -> Any:
        """
        Decode a block of data, which must result in a single message.
        """
        raise NotImplementedError

    def feed(self, data: ByteType) -> None:
        """
        Add to the codec's buffer.

        This method buffers input data (unless they belong to an
        object-in-progress). If there is no such object, this method must
        add all data to the buffer. The same holds for data that don't
        belong to the current object.
        """
        raise NotImplementedError

    def __iter__(self):
        return self

    def __next__(self):
        """
        Decode the next item in the input stream and return it.

        After calling this method, the decoder has an object in progress if
        (only if) `StopIteration` was raised.
        """
        raise NotImplementedError

    def unfeed(self, buf: VarByteType) -> int:
        """
        Take from the front of the decoder's buffer.

        This method may not be called while there is an object in progress.
        """
        raise NotImplementedError


if TYPE_CHECKING:
    EncoderFunc = Callable[[Codec, Any], ByteType | tuple[int, ByteType]]
    DecoderFunc = Callable[[Codec, ByteType], Any]


class Extension:
    def __init__(self):
        self.enc: dict[type, tuple[int | None, Callable]] = {}
        self.dec: dict[int, Callable] = {}

    def copy(self):
        res = type(self)()
        res.enc.update(self.enc)
        res.dec.update(self.dec)
        return res

    @overload
    def encoder(self, key: int | None, cls: type) -> Callable[[EncoderFunc], EncoderFunc]: ...

    @overload
    def encoder(self, key: int | None, cls: type, fn: EncoderFunc) -> EncoderFunc: ...

    def encoder(
        self, key: int | None, cls: type, fn: EncoderFunc | None = None
    ) -> EncoderFunc | Callable[[EncoderFunc], EncoderFunc]:
        def _enc(fn: EncoderFunc) -> EncoderFunc:
            self.enc[cls] = (key, fn)
            return fn

        if fn is None:
            return _enc
        return _enc(fn)

    @overload
    def decoder(self, key: int | None) -> Callable[[DecoderFunc], DecoderFunc]: ...

    @overload
    def decoder(self, key: int | None, fn: DecoderFunc) -> DecoderFunc: ...

    def decoder(
        self, key: int | None, fn: DecoderFunc | None = None
    ) -> DecoderFunc | Callable[[DecoderFunc], DecoderFunc]:
        def _dec(fn: DecoderFunc) -> DecoderFunc:
            self.dec[key] = fn  # type: ignore[index]  # key can be None for catch-all
            return fn

        if fn is None:
            return _dec
        return _dec(fn)

    def encode(self, codec: Codec, obj) -> tuple[int, ByteType]:
        try:
            key, fn = self.enc[type(obj)]
        except KeyError:
            try:
                key, fn = self.enc[object]
            except KeyError:
                raise NoCodecError(codec, obj) from None

        res = fn(codec, obj)
        if key is None:
            key, res = res
        return key, res

    def decode(self, codec: Codec, key: int, data: ByteType) -> Any:
        try:
            fn = self.dec[key]
        except KeyError:
            raise NoCodecError(codec, key) from None
        return fn(codec, data)
