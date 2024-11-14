"""Basic tests for nodes
"""
from __future__ import annotations

import pytest
import time
from base64 import b85encode

from moat.link.meta import MsgMeta
from moat.lib.codec import get_codec

def test_basic():
    codec = get_codec("cbor")

    with pytest.raises(ValueError):
        n = MsgMeta()
    name = "here"
    n = MsgMeta(name=name)
    tt = 12345
    assert n.origin == name
    assert time.time()-.1 <= n.timestamp  <= time.time()+.1
    n.timestamp = tt

    ts = b85encode(codec.encode(tt)).decode("utf-8")
    s1 = f"{name}\\{ts}"
    assert n.encode() == s1

    nn = MsgMeta.decode("unknown", s1)
    assert n == nn
    assert nn.a[0] == n.origin == nn.origin
    assert nn.a[1] == n.timestamp == nn.timestamp == tt

def test_dict():
    codec = get_codec("cbor")

    md = "\\"+b85encode(codec.encode({"yes":True,"no":False})).decode("utf-8")
    nn = MsgMeta.decode("duh", md)
    assert nn.kw["yes"] is True
    assert nn.kw["no"] is False
    assert nn.origin == "duh"
    assert time.time()-.1 <= nn.timestamp  <= time.time()+.1

def test_bad():
    n = MsgMeta("duh")
    with pytest.raises(ValueError):
        n.origin = "here|now"
    # works in a dict
    n["doc"] = "escaped\\ntext"
    # but not in the array
    with pytest.raises(ValueError):
        n[2] = "escaped\\ntext"
    # this works
    n["doc"] = b"escaped\\ntext"
    # but this doesn't
    with pytest.raises(ValueError):
        n.origin = b"not text"
    # this is broken but not checked
    n.timestamp = b'1234'
