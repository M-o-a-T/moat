from __future__ import annotations  # noqa: D100

import math
import sys

if "/src/moat" not in sys.path:
    sys.path.insert(0, "/src/moat")

from moat.cad import Slider

sq = math.sqrt(2)

r = Slider(15, 10)
