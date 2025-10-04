from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, Self

    ByteType = bytes | bytearray | memoryview[bytes]
    VarByteType = bytearray | memoryview[bytes]


class NoCodecError(ValueError):
    "No codec found"


class IncompleteData(ValueError):
    "Stream chopped off"


class Codec:
    """
    Base class for en/decoding.

    Override encode+decode for basic codecs.

    Incremental codecs which return objects need to support interleaved operation.

    In practice this means that `feed` must not start decoding and
    `__next__` must return the first object and leave the rest of the input
    buffer.

    Also, `unfeed` must return bytes from the start of the buffer.

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

        If @final is set, there must be no residual data left after one
        iteration.

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


class Extension:
    def __init__(self):
        self.enc: dict[type, tuple[int | None, Callable]] = {}
        self.dec: dict[int, Callable] = {}

    def copy(self):
        res = type(self)()
        res.enc.update(self.enc)
        res.dec.update(self.dec)
        return res

    def encoder(self, key: int | None, cls: type, fn=None) -> None | Callable:
        def _enc(fn):
            self.enc[cls] = (key, fn)
            return fn

        if fn is None:
            return _enc
        else:
            _enc(fn)

    def decoder(self, key: int, fn=None) -> None | Callable:
        def _dec(fn):
            self.dec[key] = fn
            return fn

        if fn is None:
            return _dec
        else:
            _dec(fn)

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
