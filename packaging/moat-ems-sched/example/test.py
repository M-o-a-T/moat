#!/usr/bin/python

# Invent a typical day

from moat.bms.sched import Hardware, FutureData, Model


def F(price, load, pv):
    return FutureData(price_buy=(price + 0.2) * 1.2, price_sell=price, load=load, pv=pv)


data = [
    F(0.20, 1.0, 0.0),  # 0
    F(0.18, 1.0, 0.0),
    F(0.18, 1.0, 0.0),
    F(0.15, 1.0, 0.0),
    F(0.15, 1.0, 0.0),
    F(0.20, 1.0, 0.0),
    F(0.35, 1.0, 0.0),  # 6
    F(0.40, 2.0, 0.0),
    F(0.30, 2.0, 0.5),
    F(0.25, 1.0, 1.0),
    F(0.20, 1.0, 2.0),
    F(0.05, 1.0, 3.0),
    F(0.05, 1.0, 6.0),  # 12
    F(0.05, 2.0, 8.0),
    F(0.05, 2.0, 8.0),
    F(0.15, 1.0, 4.0),
    F(0.20, 1.0, 2.0),
    F(0.35, 1.0, 1.0),
    F(0.50, 1.0, 0.0),  # 18
    F(0.55, 1.0, 0.0),
    F(0.35, 1.0, 0.0),
    F(0.30, 1.0, 0.0),
    F(0.30, 1.0, 0.0),
    F(0.25, 1.0, 0.0),  # 23
]

b = Hardware(capacity=14, batt_max_chg=5, batt_max_dis=8, inv_max_dis=10, inv_max_chg=10)
soc = 0.3
msum = 0
for n in range(100):
    grid, soc, money = Model(b, data).propose(soc)
    print(f"{n:2d} {grid:5.0f} {soc:.3f} {money:6.2f}")
    if soc < 0.06:
        soc = 0.06
    elif soc > 0.94:
        soc = 0.94
    msum += money

    data = data[1:] + data[:1]
print(f"{msum:6.2f}")
