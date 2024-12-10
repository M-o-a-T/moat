from distkv.util import attrdict, Path

CFG = attrdict(
    # Storage path for bus devices
    prefix=Path(".distkv", "moat", "bus"),

    # MQTT channel to relay bus messages
    topic=Path("moat", "bus", "data"),

    # address assignment processing default
    addr=attrdict(
        timeout=5,
        interval=100,
    ),
)
