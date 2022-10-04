#!/usr/bin/python

# Invent a typical day

from moat.bms.scheduler import Battery,FutureData,propose

def F(price, load, pv):
    f = FutureData()
    f.price_buy=(price+.2)*1.2
    f.price_sell=price
    f.load=load*1000
    f.pv=pv*1000
    return f

data = [
    F(0.20, 1.0, 0.0), # 0
    F(0.18, 1.0, 0.0),
    F(0.18, 1.0, 0.0),
    F(0.15, 1.0, 0.0),
    F(0.15, 1.0, 0.0),
    F(0.20, 1.0, 0.0),
    F(0.35, 1.0, 0.0), # 6
    F(0.40, 2.0, 0.0),
    F(0.30, 2.0, 0.5),
    F(0.25, 1.0, 1.0),
    F(0.20, 1.0, 2.0),
    F(0.05, 1.0, 3.0),
    F(0.05, 1.0, 6.0), # 12
    F(0.05, 1.0, 8.0),
    F(0.05, 1.0, 8.0),
    F(0.15, 1.0, 4.0),
    F(0.20, 1.0, 2.0),
    F(0.35, 1.0, 1.0),
    F(0.40, 2.0, 0.0), # 18
    F(0.45, 2.0, 0.0),
    F(0.35, 1.0, 0.0),
    F(0.30, 1.0, 0.0),
    F(0.30, 1.0, 0.0),
    F(0.25, 1.0, 0.0), # 23
]

b = Battery(current_charge=0.3, capacity=14000, charging_power_limit=5000, discharging_power_limit=-8000, charging_efficiency=0.9,discharging_efficiency=0.9)
for n in range(200):
    soc = propose(b,data)
    print(n,soc)
    if soc < 0.06:
        soc = 0.06
    elif soc > 0.94:
        soc = 0.94
    b.current_charge = soc

    data = data[1:] + data[:1]
