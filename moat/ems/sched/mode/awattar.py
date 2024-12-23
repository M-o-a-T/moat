"""
Germany: Get next-day prices from awattar.de API
"""

from __future__ import annotations

import asks

from . import BaseLoader


class Loader(BaseLoader):
    """
    Next-day spot market prices for Germany.

    Source: Awattar.
    """

    @staticmethod
    async def price_sell(cfg, t):
        """
        Read prices for the German next-day spot market from the Awattar API.
        """
        start = t - 24 * 3600
        end = start + 7 * 24 * 3600
        factor = cfg.data.awattar.factor
        offset = cfg.data.awattar.offset

        async with asks.sessions.Session() as s:
            r = await s.get(cfg.data.awattar.url, params=dict(start=start * 1000, end=end * 1000))
            dd = r.json()["data"]
            for d in dd[24:]:
                val = d["marketprice"] * factor + offset
                for _ in range(cfg.steps):
                    yield val

        # Somewhat primitive linear interpolation from past data
        for _ in range(cfg.data.awattar.extend):
            s = len(dd) - 24
            dv = dd[-25]["marketplace"] - dd[-1]["marketplace"]
            for i in range(24):
                val = (dd[-24 + i]["marketplace"] - dv * (25 - i) / 25) * factor + offset
                for _ in range(cfg.steps):
                    yield val
