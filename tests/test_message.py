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
@pytest.mark.parametrize("src", [2,33,-1])
@pytest.mark.parametrize("dst", [1,44,-2])
@pytest.mark.parametrize("bits", [ones,zeroes,seq])
def test_frame(length,frame,src,dst,bits):
    i = BusMessage()
    d = bits(length)
    i.start_send()
    i.send_data(d)
    assert i.data == d
    i.src = src
    i.dst = dst
    code = 2 if src<0 and dst<0 else 252 if src>=0 and dst>=0 else 30
    i.code = code

    j = BusMessage()
    i.start_extract()
    j.start_add()
    while True:
        x = i.extract_chunk(frame)
        if x is None:
            break
        j.add_chunk(x, frame)

    j.align()
    assert j.data == d
    assert j.src == src
    assert j.dst == dst
    assert j.code == code
