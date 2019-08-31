from distkv.util import attrdict

CFG = attrdict(
        prefix=('.distkv','wago'),
        # There is no "server" entry, that's stored in the DistKV node
        server_default=attrdict(
            port=29995,
        ),

        interval=1,  # for counter reporting
        poll=1,  # poll frequency
        count=True,  # Pulses up/down/both; default Up
    )

