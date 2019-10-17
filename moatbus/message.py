"""
Message structure for MoatBus
"""

from typing import Union
from bitstring import BitArray
from enum import Enum

import crcmod
CRC8 = crcmod.Crc(0x197,rev=False)
CRC16 = crcmod.Crc(0x1BAAD,rev=False)

class CRCError(RuntimeError):
    pass

class BusMessage:
    dst:int = None
    src:int = None

    code:int = None

    data:BitArray = None
    with_crc = None

    def __init__(self):
        """
        Set up an empty buffer.
        """
        self._data = BitArray()

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, " ".join("%s=%s"%(k,v) for k,v
            in vars(self).items()))
    @property
    def header(self) -> BitArray:
        """
        Return the header bytes.
        """
        buf = BitArray()
        for adr in (self.dst, self.src):
            if adr < 4:
                # 3 bit source
                buf.append('0b1')
                buf.append(BitArray(uint=adr, length=2))
            else:
                buf.append('0b0')
                buf.append(BitArray(uint=adr-4, length=7))

        # The code fills to the next byte
        buf.append(BitArray(uint=self.code, length=8-(buf.length&7)))
        return buf

    @property
    def header_len(self) -> int:
        """
        Return the header length.
        """
        h_len = 5
        for adr in (self,dst, self.src):
            h_len += 3 if adr < 4 else 8
        return h_len//8+1

    def pull_bits(self, off):
        hdr = self.header
        if off > 0:
            return hdr + self._data[:off]
        else:
            return hdr[:hdr.length+off]

    def add_crc(self, frame_len):
        """
        Add CRC to frame. @frame_len is bits per frame.
        """
        assert self.with_crc is False

        msg_bits = self._data.length + 1 // required as remainder indicator

        if self._data.length & 7:
            self._data.append(uint=0,length=8-(self._data.length & 7))
        crc = CRC8 if self._data.len//8 < 8 else CRC16
        crc = crc.new()
        crc.update(self.header.bytes)
        crc.update(self._data.bytes)
        self._data.append(crc.digest())
        self.with_crc = True

    def check_crc(self):
        """
        On an incoming message, remove residual data, check that the CRC is
        correct, and remove it.
        """
        assert self.with_crc
        crc = CRC8 if self._data.length//8 < 10 else CRC16
        crc = crc.new()
        crc.update(self.header.bytes)

        bits = self._data.length
        bits -= (bits&7)
        bits -= 8 # ignore the last byte, for now
        crc.update(self._data[:bits].bytes)
        chop = 0

        # If the frame has been stuffed, the CRC is zero before adding the
        # stuffing. Otherwise it can't be since \xFF is not a fixed point
        # of the CRC function. (Zero is, if the value is zero, which is why
        # we dont use it.)
        if crc.crcValue or self._data[bits:bits+8].bytes != b'\xFF':
            crc.update(self._data[bits:bits+8].bytes)
            bits += 8
        if crc.crcValue:
            return False

        del self._data[bits-8*crc.digest_size:]
        self.with_crc = False
        return True


    def start_extract(self):
        """
        Start extracting chunks from this buffer.
        """
        self.chunk_offset = 0
        if self.with_crc is False:
            self.generate_crc()
        assert self.with_crc is True
        self.hdr_data = BitArray(self.header)

    def extract_chunk(self, frame_bits):
        """
        Extract the @pos'th chunk of @length bits from the data stream.
        """
        offset = self.chunk_offset+frame_bits
        if self.hdr_data is not None:
            res = self.hdr_data[self.chunk_offset:offset]
            if res.length < frame_bits:
                res.append(self._data[:frame_bits-res.length])
                if res.length+self.chunk_offset >= self.hdr_data.length:
                    offset = res.length+self.chunk_offset - self.hdr_data.length
                    self.hdr_data = None
        else:
            res = self._data[self.chunk_offset:offset]
        if res.length == 0:
            return None
        elif res.length < frame_bits:
            res.append(BitArray(int=-1, length=frame_bits-res.length))
            # We stuff with ones, not zeroes, so that the CRC can discover
            # our stuffing later

        self.chunk_offset = offset
        return res.uint

    def start_add(self):
        assert self.with_crc is None
        assert self._data.length == 0
        assert self.code is None
        self.with_crc = True

    def add_chunk(self,frame_bits, data):
        """
        Feed data into this buffer. (The buffer should initially be new.)

        As soon as the header is complete, it's removed from the input
        stream and available as attributes.

        A missing header is discovered by .code being `None`.

        Call `.check_crc()` when the stream ends.
        """
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
        frame_len = 3+3
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
        frame_len += 8-(frame_len&7)
        if self._data.length < frame_len:
            return

        b = self._data
        off = 0

        if b[off]:
            self.dst = b[off+1:off+3].uint
            off += 3
        else:
            self.dst = b[off+1:off+8].uint+4
            off += 8
        if b[off]:
            self.src = b[off+1:off+3].uint
            off += 3
        else:
            self.src = b[off+1:off+8].uint+4
            off += 8

        self.code = b[off:frame_len].uint
        self.with_crc = True
        del self._data[0:frame_len]

    @property
    def data(self):
        """
        Extract the current data buffer. Must not have a CRC attached.
        """
        assert not self.with_crc
        return self._data.bytes

    def start_send(self):
        """
        Start adding data to be sent to this message.

        The buffer is usually new, but in any case it must not have a CRC.
        """
        assert not self.with_crc
        self.with_crc = False

    def send_data(self, data):
        """
        Add data (bytes) to this message.

        The buffer is stuffed with zeroes if not on a byte boundary.
        """
        assert self.with_crc is False
        if self._data.length & 7:
            self._data.append(uint=0,length=8-(self._data.length & 7))
        self._data.append(data)

    def send_bits(self, **kw):
        """
        Add an arbitrary number of bits to the buffer.
        """
        assert self.with_crc is False
        self._data.append(**kw)

