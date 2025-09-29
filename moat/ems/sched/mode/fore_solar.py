"""
Get solar data from forecast.solar
"""

from __future__ import annotations

from datetime import datetime

import asks

from . import BaseLoader


class Loader(BaseLoader):
    """
    Get solar yield forceat from the "forecast.solar" API.
    """

    @staticmethod
    async def _solar(cfg, t, session, a=None):
        """
        Projected solar power, in kW.

        Config:
            data.fore_solar.url: base URL
            data.fore_solar.api: your API key
            data.fore_solar.factor: 0.001
        """

        factor = cfg.data.fore_solar.factor
        start = datetime.fromtimestamp(t - 3600, tz=datetime.UTC).strftime("%H:%M")
        t_step = int(3600 / cfg.steps)
        cmp = a["compass"]
        if cmp > 180:
            cmp -= 360

        url = (
            f"{cfg.data.fore_solar.url}/{cfg.data.fore_solar.api}/estimate/"
            f"watts/{cfg.solar.lat}/{cfg.solar.long}/{a['tilt']}/{cmp}/{int(a['peak'] * 1000)}"
        )
        r = await session.get(
            url,
            headers=dict(
                accept="application/json",
            ),
            params=dict(
                no_sun=0,
                time="seconds",
                start=start,
                damping=cfg.solar.damping,
            ),
        )
        if r.status_code >= 400:
            raise RuntimeError(r, r.content)
        kx = 0
        tn = t + t_step
        vs = 0  # value sum
        n = 0  # #values

        # If the result set is more detailed than our request, we
        # average the data.
        # If the result is less detailed, we repeat values.
        #
        # XXX there's no interpolation, thus if the result has a
        # half-hour resolution but our step size is 3/hour, the result
        # is somewhat less accurate than theoretically possible. In
        # practice this should not matter too much..
        for k, v in r.json()["result"].items():
            k = int(k)  # noqa:PLW2901
            # must be ascending
            assert k > kx
            kx = k

            if k < t:
                continue
            if k < tn:
                vs += v
                n += 1
                continue

            while k >= tn:
                t = tn
                tn += t_step

                yield vs / 1000 / n * factor
                # value is kW, thus not divided by t_step
                vs = v
                n = 1

        if n:
            for _ in range(cfg.steps):
                yield vs / 1000 / n * factor

    @classmethod
    async def solar(cls, cfg, t):
        "Collect solar input"
        async with asks.sessions.Session(connections=2) as s:
            a = [cls._solar(cfg, t, s, a) for a in cfg.solar.array]
            while True:
                val = 0
                for v in a:
                    try:
                        val += await anext(v)
                    except StopAsyncIteration:
                        return
                yield val
