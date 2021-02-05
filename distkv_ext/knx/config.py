from distkv.util import attrdict, Path

CFG = attrdict(
    prefix=Path(".distkv", "knx"),
    # There is no "server" entry, that's stored in the DistKV node
    server_default=attrdict(
        port=3671,
    ),
    poll=10,  # poll frequency: server
    count=True,  # Pulses up=True/down=False/both=None, default Up
)
