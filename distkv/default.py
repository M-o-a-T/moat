from .util import attrdict

__all__ = [
        'PORT', 'CFG', 'gen_ssl',
    ]

PORT = 27586  # 2000 + 100*ord('K') + ord('V')

CFG = attrdict(
        server=attrdict(
            host="localhost",
            port=PORT,
            ssl=False,
            # ssl=attrdict(cert='/path/to/cert.pem',key='/path/to/cert.key'),
            ),
        serf=attrdict(
            host="localhost",
            port=7373,
            ),
        state=None, # path to load/save system state

        root=":distkv", # serf user event prefix. Should start with a colon.
        domain=None, # domain in which to look up nodes

        change=attrdict(
            length=5,
            ),
        ping=attrdict(
            length=4,
            clock=5,
            ),
    )

