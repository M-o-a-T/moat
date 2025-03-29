"""
Wrapper with yaml support
"""
from ._cbor import *
from moat.util.compat import const

import ruyaml as yaml

SafeRepresenter = yaml.representer.SafeRepresenter

CBOR_TAG_CBOR_FILEHEADER = const(55799)  # single CBOR content
CBOR_TAG_CBOR_LEADER = const(55800)  # header for multiple CBOR items

def _tag_repr(dumper, data):
    return dumper.represent_list([XTag(data.tag), data.value])

class XTag:
    def __init__(self, tag):
        self.tag = tag
def _xtag_repr(dumper,data):
    if data.tag>2**28:
        try:
            tag = struct.pack(">I",data.tag).decode("ascii")
            try:
                int(tag)
            except ValueError:
                pass
            else:
                tag = str(data.tag)
        except Exception:
            breakpoint()
            tag = str(data.tag)
    else:
        tag = str(data.tag)
    return dumper.represent_scalar("!CBOR",tag)

SafeRepresenter.add_representer(Tag, _tag_repr)
SafeRepresenter.add_representer(XTag, _xtag_repr)

