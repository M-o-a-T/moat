"Basic JSON codec"

from __future__ import annotations

from ._base import Codec as _Codec

try:
    from json import dumps, loads
except ImportError:
    from simplejson import dumps, loads


class Codec(_Codec):
    "basic JSON codec"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the JSON codec")
        super().__init__()

    def encode(self, obj):
        "basic encoder"
        return dumps(obj).encode("utf-8")

    def decode(self, data):
        "basic decoder"
        return loads(data.decode("utf-8"))

    # 'feed' is not implemented:
    # there is no reasonable incremental JSON codec out there
    # bring your own framing …
