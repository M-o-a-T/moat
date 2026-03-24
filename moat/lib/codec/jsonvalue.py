"A JSON codec that encapsulates its data in a ``value`` element"

from __future__ import annotations

from .json import Codec as _Codec


class Codec(_Codec):
    "JSON codec with 'value' element"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the JSON codec")
        super().__init__()

    def encode(self, obj):
        "basic encoder"
        return super().encode({"value": obj})

    def decode(self, data):
        "basic decoder"
        return super().decode(data)["value"]

    # 'feed' is not implemented:
    # there is no reasonable incremental JSON codec out there
    # bring your own framing …
