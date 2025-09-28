"""
Charge/discharge optimizer.
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import nullcontext

from ortools.linear_solver import pywraplp

from moat.util import attrdict
from moat.util.times import humandelta, ts2iso

from .mode import Loader

logger = logging.getLogger(__name__)


async def generate_data(cfg, t):
    # loads, prices, solar, buy_factor, buy_const):
    """
    Generate data chunks from iterators
    """
    iters = {}
    for k in "price_buy,price_sell,solar,load".split(","):
        iters[k] = aiter(Loader(cfg.mode[k], k)(cfg, t))
    while True:
        val = attrdict()
        k = None
        try:
            for k, v in iters.items():
                val[k] = await anext(v)
        except StopAsyncIteration:
            logger.info("END: %s", k)
            return
        logger.debug("DATA: %r", val)
        yield val


def add_piecewise(solver, x, y, points: list[int, int], name):
    """
    Add a piecewise-linear constraint on y=a*x+b.

    @points is a list of x/y pairs to interpolate between.
    """

    # Source:
    # https://or.stackexchange.com/questions/6674/how-to-linearize-specific-range-constraints#answer-6675

    # untested

    n = len(points) - 1  # number of segments
    l = []  # noqa:E741  # lambda values to interpolate within a segment

    rx = []
    ry = []
    for i, xyi in enumerate(points):
        xi, yi = xyi
        li = solver.NumVar(0, 1, f"l_{name}_{i}")

        l.append(li)
        rx.append(xi * li)
        ry.append(yi * li)

    b = [solver.BoolVar(f"b_{name}_{i}") for i in range(n)]
    solver.Add(sum(l) == 1)  # 1: lambda values sum to 1
    solver.Add(sum(b) == 1)  # 3: we're in exactly one segment
    solver.Add(x == sum(rx))  # 2: interpolated X value
    solver.Add(y == sum(ry))  # Objective: interpolated Y value
    for i in range(n):
        solver.Add(b[i] <= l[i] + l[i + 1])
        # 4-7: when x is in segment i, the sum of the lambdas on
        # the upper and lower boundary of this segment is forced to be at
        # least 1. Because of (1) and the fact that lambda is constrained
        # to [0,1], this sum must be exactly 1 and all other lambda values
        # are thus zero.


class Model:
    """
    Calculate optimum charge/discharge behavior based on
    minimizing cost / maximizing income.

    Initial input:
    * configuration data
    * async iterator for values

    Solver input:
    * current charge level (SoC)

    Output (first period):
    * grid input (negative: send energy)
    * battery SoC at end of first period

    You should re-run the model at the start of the next period, using
    the SoC at that time.
    """

    money = None
    cap = None
    g_sell = None
    g_buy = None
    g_sells = None
    g_buys = None
    moneys = None
    caps = None
    b_diss = None
    b_chgs = None
    cap_init = None
    constr_init = None
    objective = None
    solver = None

    def __init__(self, cfg: dict, t=None):
        if t is None:
            t_slot = 3600 / cfg.steps
            t_now = time.time()
            t = t_now + t_slot / 2
            t -= t % t_slot
            if abs(t_now - t) > t_slot / 10:
                raise ValueError(
                    f"You're {humandelta(abs(t_now - t))} away from {ts2iso(t)}",
                )

        elif t % (3600 / cfg.steps):
            raise ValueError(f"Time {t} not a multiple of 3600/{cfg.steps}")
        self.cfg = cfg
        self.t = t

    async def _setup(self):
        cfg = self.cfg
        data = generate_data(cfg, self.t)
        per_hour = self.cfg.steps

        # ORtools
        self.solver = solver = pywraplp.Solver("B", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)
        self.objective = solver.Objective()
        inf = solver.infinity()

        # Starting battery charge
        self.cap_init = cap_prev = solver.NumVar(
            cfg.battery.capacity * 0.05,
            cfg.battery.capacity * 0.95,
            "b_init",
        )
        self.constr_init = solver.Constraint(0, 0)
        self.constr_init.SetCoefficient(self.cap_init, 1)

        # collect vars for reporting
        self.g_buys = []
        self.g_sells = []
        self.b_chgs = []
        self.b_diss = []
        self.caps = []
        self.moneys = []

        i = 0
        _pr = None
        while True:
            # input constraints
            try:
                dt = await anext(data)
            except StopAsyncIteration:
                break
            if dt.price_buy == dt.price_sell:
                dt.price_buy *= 1.001
            elif dt.price_buy < dt.price_sell:
                raise ValueError(f"At {i}: buy {dt.price_buy} < sell {dt.price_sell} ??")
                # TODO

            # ### Variables to consider

            # future battery charge
            cap = solver.NumVar(
                cfg.battery.capacity * cfg.battery.soc.min,
                cfg.battery.capacity * cfg.battery.soc.max,
                f"b{i}",
            )

            self.caps.append(cap)

            # battery charge/discharge
            b_chg = solver.NumVar(0, cfg.battery.max.charge / per_hour, f"bc{i}")
            b_dis = solver.NumVar(0, cfg.battery.max.discharge / per_hour, f"bd{i}")
            self.b_chgs.append(b_chg)
            self.b_diss.append(b_dis)

            # solar power input. We may not be able to take all
            s_in = solver.NumVar(0, dt.solar / per_hour, f"pv{i}")

            # inverter charge/discharge
            i_chg = solver.NumVar(0, cfg.inverter.max.charge / per_hour, f"ic{i}")
            i_dis = solver.NumVar(0, cfg.inverter.max.discharge / per_hour, f"id{i}")

            # local load
            l_out = solver.NumVar(dt.load / per_hour, dt.load / per_hour, f"ld{i}")

            # grid
            g_buy = solver.NumVar(0, cfg.grid.max.buy / per_hour, f"gi{i}")
            g_sell = solver.NumVar(0, cfg.grid.max.sell / per_hour, f"go{i}")
            self.g_buys.append(g_buy)
            self.g_sells.append(g_sell)

            # income to maximize
            money = solver.NumVar(-inf, inf, f"pr{i}")
            self.moneys.append(money)

            # ### Constraints (actually Relationships, as they're all equalities)

            # Battery charge. old + charge - discharge == new, so … - new == 0.
            solver.Add(cap_prev + cfg.battery.efficiency.charge * b_chg - b_dis == cap)

            # DC power bar. power_in == power_out
            solver.Add(
                s_in
                + cfg.battery.efficiency.discharge * b_dis
                + cfg.inverter.efficiency.charge * i_chg
                == b_chg + i_dis,
            )

            # AC power bar. power_in == power_out
            solver.Add(g_buy + cfg.inverter.efficiency.discharge * i_dis == g_sell + l_out + i_chg)

            # Money earned: grid_out*price_sell - grid_in*price_buy
            solver.Add(
                dt.price_sell * g_sell
                - dt.price_buy * g_buy
                + cap
                * cfg.battery.soc.value.current
                / cfg.battery.capacity  # bias for keeping the battery charged
                == money,
            )

            self.objective.SetCoefficient(money, 1)
            cap_prev = cap
            if not i:
                self.g_buy, self.g_sell = g_buy, g_sell
                self.cap = cap
                self.money = money
            i += 1

        # Attribute a fake monetary value of ending up with a charged battery
        self.objective.SetCoefficient(cap, cfg.battery.soc.value.end / cfg.battery.capacity)

        self.objective.SetMaximization()

    async def propose(self, charge):
        """
        Assuming that the current SoC is @charge, return
        - how much power to take from / -feed to the grid [W]
        - the SoC at the end of the current period [0…1]
        - this period's earnings / -cost [$$]

        """
        await self._setup()
        cfg = self.cfg

        charge *= cfg.battery.capacity
        self.constr_init.SetLb(charge)
        self.constr_init.SetUb(charge)

        self.solver.Solve()

        async with anyio.create_task_group() as tg:
            res = cfg.mode.result
            if res is not None:
                res = Loader(res).result

            res2 = cfg.mode.results
            if res2 is not None:
                sch, rch = anyio.create_memory_object_stream(1)
                tg.start_soon(Loader(res2).results, cfg, rch)
                res2 = sch

            async with res2 if res2 is not None else nullcontext():
                for g_buy, g_sell, b_chg, b_dis, cap, money in zip(
                    self.g_buys,
                    self.g_sells,
                    self.b_chgs,
                    self.b_diss,
                    self.caps,
                    self.moneys,
                    strict=False,
                ):
                    val = dict(
                        grid=(g_buy.solution_value() - g_sell.solution_value()) * cfg.steps,
                        soc=cap.solution_value() / cfg.battery.capacity,
                        batt=b_chg.solution_value() - b_dis.solution_value(),
                        money=money.solution_value(),
                    )

                    if res is not None:
                        tg.start_soon(res, cfg, val)
                        res = None
                        if res2 is None:
                            break

                    if res2 is not None:
                        await res2.send(val)
