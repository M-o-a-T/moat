"""
Base object for scheduling
"""

from __future__ import annotations

from moat.util import load_ext


class BaseLoader:
    """
    Describe how to load various scheduling data.
    """

    @staticmethod
    async def price_buy(cfg, t):
        """
        Future prices for incoming energy, in $$$/kWh.
        """
        raise NotImplementedError("You need to add a static 'price_buy' method")

    @staticmethod
    async def price_sell(cfg, t):
        """
        Future prices for sold energy, in $$$/kWh.
        """
        raise NotImplementedError("You need to add a static 'price_sell' method")

    @staticmethod
    async def solar(cfg, t):
        """
        Projected solar power, in kW.
        """
        raise NotImplementedError("You need to add a static 'solar' method")

    @staticmethod
    async def load(cfg, t):
        """
        Projected local consumption, in kW.
        """
        raise NotImplementedError("You need to add a static 'load' method")

    @staticmethod
    async def soc(cfg):
        """
        The battery's current SoC.
        """
        res = cfg.bms.sched.start.soc
        if res < 0:
            raise NotImplementedError("You need to set the 'start.soc' parameter")
        return res

    @staticmethod
    async def result(cfg, **kw):
        """
        Accepts the intended state at the end of the first period.
        power to/from the grid and intended SoC.
        """
        raise NotImplementedError("You need to add a static 'result' method")

    @staticmethod
    async def results(cfg, it):
        """
        Accepts an iterator for intended results over all periods.

        By default this does nothing.
        """
        pass  # pylint:disable=unnecessary-pass


def Loader(name, key=None):
    """Fetch a named loader class"""
    res = load_ext(f"moat.bms.sched.mode.{name}")
    if res is None:
        raise AttributeError(name)
    res = res.Loader
    if key is not None:
        res = getattr(res, key)
    return res
