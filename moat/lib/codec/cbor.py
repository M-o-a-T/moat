"""
Wrapper for CBOR support
"""

from __future__ import annotations

import struct

import ruyaml as yaml

from moat.util.compat import const

from ._cbor import Codec, Tag  # noqa:F401

SafeRepresenter = yaml.representer.SafeRepresenter  # pyright:ignore

CBOR_TAG_CBOR_FILEHEADER = const(55799)  # single CBOR content
CBOR_TAG_CBOR_LEADER = const(55800)  # header for multiple CBOR items


def _tag_repr(dumper, data):
    return dumper.represent_list([XTag(data.tag), data.value])


class XTag:  # noqa: D101
    def __init__(self, tag):
        self.tag = tag


def _xtag_repr(dumper, data):
    if data.tag > 2**28:
        try:
            tag = struct.pack(">I", data.tag).decode("ascii")
            try:
                int(tag)
            except ValueError:
                pass
            else:
                tag = str(data.tag)
        except Exception:
            tag = str(data.tag)
    else:
        tag = str(data.tag)
    return dumper.represent_scalar("!CBOR", tag)


SafeRepresenter.add_representer(Tag, _tag_repr)
SafeRepresenter.add_representer(XTag, _xtag_repr)
