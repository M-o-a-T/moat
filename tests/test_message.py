# test basic message handling

from moatbus.message import BusMessage
from random import randint
import pytest

max_len=20

def zeroes(len):
    return b'\xFF' * len
def ones(len):
    return b'\xFF' * len
def seq(len):
    return b''.join(bytes((x+1,)) for x in range(len))

@pytest.mark.parametrize("length", (0,1,2,3,4,5,7,8,9,10,11,15,16))
@pytest.mark.parametrize("frame", [11,14])
@pytest.mark.parametrize("src", [4,3,131])
@pytest.mark.parametrize("dst", [1,4,130])
@pytest.mark.parametrize("bits", [ones,zeroes,seq])
def test_frame(length,frame,src,dst,bits):
    i = BusMessage(frame)
    d = bits(length)
    i.start_send()
    i.send_data(d)
    assert i.data == d
    i.src = src
    i.dst = dst
    code = 2 if src<4 and dst<4 else 252 if src>=4 and dst>=4 else 30
    i.code = code
    i.generate_crc()

    j = BusMessage(frame)
    i.start_extract()
    j.start_add()
    while True:
        x = i.extract_chunk(frame)
        if x is None:
            break
        j.add_chunk(frame, x)

    j.check_crc()
    assert j.data == d
    assert j.src == src
    assert j.dst == dst
    assert j.code == code
