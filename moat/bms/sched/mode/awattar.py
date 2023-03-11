import anyio
from . import Loader as _Loader
from . import BaseLoader

from datetime import datetime,timedelta,timezone
import asks
from pprint import pprint

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
        tz = datetime.now(timezone(timedelta(0))).astimezone().tzinfo
        start = t-24*3600
        end = start+7*24*3600
        factor = cfg.data.awattar.factor
        offset = cfg.data.awattar.offset

        async with asks.sessions.Session() as s:
            r = await s.get(cfg.data.awattar.url,params=dict(start=start*1000, end=end*1000))
            dd = r.json()["data"]
            for d in dd:
                yield d["marketprice"] / factor + offset

