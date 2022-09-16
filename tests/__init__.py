import anyio

import logging
logging.basicConfig(level=logging.DEBUG)


def anyio_run(p, *a, **k):
    if "backend" not in k:
        k["backend"] = "trio"
    return anyio.run(p, *a, **k)


