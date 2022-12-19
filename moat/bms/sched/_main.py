#!/usr/bin/env python3
"""
Basic tool support

"""
import logging  # pylint: disable=wrong-import-position

import asyncclick as click
from moat.util import yload

from .control import FutureData, Model
from .hardware import Hardware

log = logging.getLogger()

par = (
    Hardware.__doc__
    + """\
buy_factor: multiplier for bought over sold energy, default 1.01
buy_const: price per kWh in addition to price point, default 0.1
"""
)


@click.group()
async def cli():
    """Battery Manager: Scheduling"""
    pass  # pylint: disable=unnecessary-pass


def fd_gen(loads, prices, solar, buy_factor, buy_const):
    """
    Generate future data objects from iterators
    """
    loads = iter(loads)
    prices = iter(prices)
    solar = iter(solar)
    while True:
        try:
            ld = float(next(loads))
            pr = float(next(prices))
            so = float(next(solar))
        except StopIteration:
            return
        fd = FutureData(load=ld, pv=so, price_sell=pr, price_buy=pr * buy_factor + buy_const)
        yield fd


@cli.command(
    help="""
Calculate proposed SoC by analyzing files with assumed future usage and weather / solar input.
Goal: minimize cost.
"""
)
@click.option("-p", "--params", type=click.File("r"), help="System parameters")
@click.option(
    "-c", "--cost-final", type=float, help="cost of empty battery at end, default=0", default=0
)
@click.option(
    "-C",
    "--cost-interim",
    type=float,
    help="cost of empty battery during a cycle, default=0",
    default=0,
)
@click.option("-L", "--loads", type=click.File("r"), help="Predicted load data", required=True)
@click.option(
    "-P", "--prices", type=click.File("r"), help="Future power prices per kWh", required=True
)
@click.option("-S", "--solar", type=click.File("r"), help="Predicted solar inputs", required=True)
@click.option(
    "-s", "--soc", "soc_cur", type=float, help="current SoC (0…1, default 0.5)", default=0.5
)
@click.option("-n", "--steps", type=int, help="steps per hour, default 1", default=1)
@click.option(
    "-a", "--all", "all_", is_flag=True, help="emit all outputs (default: first interval)"
)
def analyze(params, cost_final, cost_interim, loads, prices, solar, soc_cur, steps, all_):
    """
    Analyze a file w/ future data.
    """
    params = yload(params, attr=True).system
    data = fd_gen(loads, prices, solar, params.buy_factor, params.buy_const)
    hw = Hardware()
    for k in dir(hw):
        if k[0] == "_" or k not in params:
            continue
        setattr(hw, k, params[k])
    m = Model(hw, data, per_hour=steps, chg_inter=cost_interim, chg_last=cost_final)
    if all_:
        for grid, soc, money in m.proposed(soc_cur):
            print(grid, soc, money)
    else:
        grid, soc, money = m.propose(soc_cur)
        print(grid, soc, money)
