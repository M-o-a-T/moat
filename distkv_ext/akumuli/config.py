from distkv.util import attrdict

CFG = attrdict(
        prefix=('.distkv','akumuli'),
        # There is no "server" entry, that's stored in the DistKV node
        server_default=attrdict(
            port=8282,
        ),
    )

