from distkv.util import attrdict, Path

CFG = attrdict(
    prefix=Path(".distkv", "gpio"),
    interval=1,  # input/count: Pulse reporting frequency
    count=True,  # input/count, input/button: Pulse direction
    # up down both=True False None
    low=False,  # if True, the default is active-low
    flow=False,  # if True, send intermediate results
    skip=True,  # ignore signals < t_bounce
    t_idle=1.5,  # input/button: max pulse width
    t_clear=30,  # button: set to None after this
    t_bounce=0.05,  # input/button: min pulse width
)
