from distkv.util import attrdict

CFG = attrdict(
    prefix=(".distkv", "wago"),
    # There is no "server" entry, that's stored in the DistKV node
    server_default=attrdict(port=29995,),
    poll=0.1,  # poll frequency: server
    ping=5,  # ping frequency: server
    interval=1,  # for counter reporting: port
    count=True,  # Pulses up=True/down=False/both=None, default Up: port
)
