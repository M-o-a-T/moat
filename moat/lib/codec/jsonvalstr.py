"A JSON+Value codec that uses a stringified element"

from __future__ import annotations

import json

from .jsonvalue import Codec as _Codec


class Codec(_Codec):
    "JSON+Value using a stringified element"

    def __init__(self, ext=None):
        if ext is not None:
            raise ValueError("You can't extend the JSON codec")
        super().__init__()

    def encode(self, obj):
        "basic encoder"
        return super().encode(json.dumps(obj))

    def decode(self, data):
        "basic decoder"
        return json.loads(super().decode(data))

    # 'feed' is not implemented:
    # there is no reasonable incremental JSON codec out there
    # bring your own framing …
