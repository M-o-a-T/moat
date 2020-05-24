from distkv.util import attrdict

CFG = attrdict(
        prefix=('.distkv','gpio'),
        interval=1,  # for counter reporting: port
        count=True,  # Pulses up=True/down=False/both=None, default Up: port
    )

