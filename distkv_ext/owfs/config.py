from distkv.util import attrdict

CFG = attrdict(
        prefix=('.distkv','onewire'),
        server=[{}],
        server_default=attrdict(
            host="localhost",
            port=4304,
        ),
    )

