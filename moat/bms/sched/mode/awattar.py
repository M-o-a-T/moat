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
    async def price_sell(cfg):
        """
        Read prices for the German next-day spot market from the Awattar API.
        """
        tz = datetime.now(timezone(timedelta(0))).astimezone().tzinfo
        start = datetime.now().astimezone(tz).replace(minute=0,second=0)
        end = start+timedelta(days=7)
        factor = cfg.data.awattar.factor
        offset = cfg.data.awattar.offset

        async with asks.sessions.Session() as s:
            r = await s.get(cfg.data.awattar.url,params=dict(start=int(start.timestamp())*1000, end=int(end.timestamp())*1000))
            dd = r.json()["data"]
            for d in dd:
                yield d["marketprice"] / factor + offset

