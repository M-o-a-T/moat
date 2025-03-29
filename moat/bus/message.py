"""
Message structure for MoatBus
"""

from __future__ import annotations

from bitstring import BitArray
from distkv.util import attrdict


class LongMessageError:
    """
    Message is too long.
    """

    pass


class BusMessage:
    dst: int = None
    src: int = None

    code: int = None
    prio: int = None

    data: BitArray = None

    _attrs = tuple("src dst code data".split())

    def __init__(
        self,
        src: int | None = None,
        dst: int | None = None,
        code: int | None = None,
        data: bytes | None = None,
        prio: int = 1,
    ):
        """
        Set up an empty buffer.
        """
        self.src = src
        self.dst = dst
        self.code = code
        self.prio = prio
        self._data = BitArray(data)

    def decode(self, spec=None):
        res = attrdict()
        if self.src == -4:
            res.src = "B"
        elif self.src < 0:
            res.src = f"S{self.src + 4}"
        else:
            res.src = self.src
        if self.dst == -4:
            res.dst = "B"
        elif self.dst < 0:
            res.dst = f"S{self.dst + 4}"
        else:
            res.dst = self.dst
        res.prio = self.prio
        res.code = self.code

        if self.code == 0:
            cmd = self._data[0] & 0x7
            if cmd == 0:  ## AA
                res.cmd = "Address"
            elif cmd == 1:  ## Poll
                res.cmd = "poll"
            elif cmd == 2:  ## Console
                res.cmd = "console"
            elif cmd == 5:  ## Firmware
                res.cmd = "update"
            elif cmd == 6:  ## test
                res.cmd = "test"
            elif cmd == 7:  ## reset
                res.cmd = "Reset"
            else:
                res.cmd = f"Cmd ?{cmd}"

        elif self.code == 1 and self.src < 0 and self.dst >= 0:  # dir
            res.cmd = "dir"
        elif self.code == 2 and self.src < 0 and self.dst >= 0:  # read
            res.cmd = "read"
        elif self.code == 3 and self.src < 0 and self.dst >= 0:  # write
            res.cmd = "write"
        else:
            res.cmd = f"?{self.code}"
        return res

    def __eq__(self, other):
        return all(getattr(self, a) == getattr(other, a) for a in self._attrs)

    def __hash__(self):
        return hash(tuple(getattr(self, a) for a in self._attrs))

    def __repr__(self):
        return "<{}: {}>".format(
            self.__class__.__name__,
            " ".join(f"{k}={v}" for k, v in vars(self).items()),
        )

    def __len__(self):
        return len(self.data) >> 3

    @property
    def header(self) -> BitArray:
        """
        Return the header bytes.
        """
        buf = BitArray()
        for adr in (self.dst, self.src):
            if adr < 0:
                # 3 bit source
                buf.append("0b1")
                buf.append(BitArray(uint=adr + 4, length=2))
            else:
                buf.append("0b0")
                buf.append(BitArray(uint=adr, length=7))

        # The code fills to the next byte
        buf.append(BitArray(uint=self.code, length=8 - (buf.length & 7)))
        return buf

    @property
    def header_len(self) -> int:
        """
        Return the header length.
        """
        if self.dst < 0 and self.src < 0:
            return 1
        elif self.dst > 0 and self.src > 0:
            return 3
        else:
            return 2

    def first_bits(self, off):
        """
        Return the first @off bits
        """
        hdr = self.header
        if off > hdr.length:
            return hdr + self._data[: off - hdr.length]
        else:
            return hdr[:off]

    ## sender

    def start_send(self):
        """
        Start adding data to be sent to this message.

        The buffer is usually new.
        """
        pass

    def add_data(self, data):
        """
        Add data (bytes) to this message.

        The buffer is stuffed with zeroes if not on a byte boundary.

        This is synonymous to `buf += b"data"`.
        """
        if self._data.length & 7:
            self._data.append(uint=0, length=8 - (self._data.length & 7))
        self._data.append(data)

    __iadd__ = add_data

    def send_bits(self, **kw):
        """
        Add an arbitrary number of bits to the buffer.
        """
        self._data.append(**kw)

    def start_extract(self):
        """
        Start extracting chunks from this buffer.
        """
        self.chunk_offset = 0
        self.hdr_data = self.header

    def extract_chunk(self, frame_bits):
        """
        Extract the next chunk of @length bits from the data stream.

        The last value may be extended.

        Returns None if the message has ended.
        """
        offset = self.chunk_offset + frame_bits  # end of to-be-extracted part

        if self.hdr_data is not None:
            hdr_len = self.hdr_data.length
            if self.chunk_offset >= hdr_len:
                res = self._data[self.chunk_offset - hdr_len : offset - hdr_len]
            else:
                if offset <= hdr_len:
                    res = self.hdr_data[self.chunk_offset : offset]
                else:
                    res = self.hdr_data[self.chunk_offset :] + self._data[: offset - hdr_len]

        else:
            res = self._data[self.chunk_offset : offset]

        if res.length == 0:
            return None
        elif res.length < frame_bits:
            if frame_bits - res.length >= 8:
                # Send residual bits as excess value
                res = (res.uint << (frame_bits - res.length - 8)) | (1 << frame_bits)
            else:
                # pad frame with zero bits
                res = res.uint << (frame_bits - res.length)
        else:
            res = res.uint

        self.chunk_offset = offset
        return res

    ## receiver

    def start_add(self):
        assert self._data.length == 0
        assert self.code is None

    def add_chunk(self, data, frame_bits):
        """
        Feed data into this buffer. (The buffer should initially be new.)

        As soon as the header is complete, it's removed from the input
        stream and available as attributes.

        A missing header is discovered by .code being `None`.
        """
        if data & (1 << frame_bits):
            frame_bits -= 8
            data &= (1 << frame_bits) - 1
        self._data += BitArray(uint=data, length=frame_bits)

        if self.code is None:
            self._gen_code()

    def add_written(self, data):
        """
        Feed data into this buffer. (The buffer should initially be new.)

        This is like `add_chunk` but accepts a BitArray. It's intended for
        switching a writer to a reader, as it needs to feed the data it has
        acquired to a new message.
        """
        self._data += data

        if self.code is None:
            self._gen_code()

    def _gen_code(self):
        frame_len = 3 + 3
        b = self._data
        if not b.length:
            return
        if not b[0]:
            frame_len += 5
            if b.length <= 8:
                return
            if not b[8]:
                frame_len += 5
        else:
            if b.length <= 3:
                return
            if not b[3]:
                frame_len += 5
        frame_len += 8 - (frame_len & 7)
        if self._data.length < frame_len:
            return

        b = self._data
        off = 0

        if b[off]:
            self.dst = b[off + 1 : off + 3].uint - 4
            off += 3
        else:
            self.dst = b[off + 1 : off + 8].uint
            off += 8
        if b[off]:
            self.src = b[off + 1 : off + 3].uint - 4
            off += 3
        else:
            self.src = b[off + 1 : off + 8].uint
            off += 8

        self.code = b[off:frame_len].uint
        del self._data[0:frame_len]

    @property
    def data(self):
        """
        Extract the current data buffer.
        """
        return self._data.bytes

    def align(self):
        n = self._data.length % 8
        if n:
            del self._data[-n:]
