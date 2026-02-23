"""
Test runner
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

import moat.micro
from moat.util import attrdict
from moat.lib.codec import get_codec
from moat.lib.rpc._test import temp_dir

# from moat.micro.main import Request, get_link, get_link_serial
# from moat.micro.proto.multiplex import Multiplexer
from moat.lib.stream import ProcessBuf

required = [
    "__future__",
    "copy",
    "errno",
    "pprint",
    "typing",
    "types",
    "functools",
    "contextlib",
    "ucontextlib",
    "collections",
    "inspect",
]


def rlink(s, d):
    "recursive linking"
    if s.is_file():
        with suppress(FileExistsError):
            d.symlink_to(s)
    else:
        with suppress(FileExistsError):
            d.mkdir()
        for f in s.iterdir():
            rlink(s / f.name, d / f.name)


class MpyBuf(ProcessBuf):
    """
    A stream that links to MicroPython.

    Parameters:
        dupterm(bool): Use a MPy variant that supports dupterm.
                       The downside is that such a variant currently
                       does not support writing to stderr …
    """

    async def setup(self):
        codec = get_codec("std-cbor")
        dupterm = self.cfg.get("dupterm", False)
        pre = Path(__file__).parents[2]
        upy = pre / "ext/micropython"

        root = self.cfg.get("cwd", None)
        if root is None:
            root = temp_dir.get() / "root"
        else:
            root = Path(root).absolute()
        lib = root / "stdlib"
        lib2 = root / "lib"
        with suppress(FileExistsError):
            root.mkdir()
        with suppress(FileExistsError):
            lib.mkdir()
        with suppress(FileExistsError):
            lib2.mkdir()
        with suppress(FileExistsError):
            (root / "tests").symlink_to(Path("tests").absolute())

        std = (upy / "lib/micropython-lib/python-stdlib").absolute()
        ustd = (upy / "lib/micropython-lib/micropython").absolute()
        for req in required:
            if (std / req).exists():
                rlink(std / req, lib)
            elif (ustd / req).exists():
                rlink(ustd / req, lib)
            else:
                raise FileNotFoundError(std / req)

        aio = Path("lib/micropython/extmod/asyncio").absolute()
        with suppress(FileExistsError):
            (lib / "asyncio").symlink_to(aio)

        libp = []
        for p in moat.micro.__path__:
            p = Path(p) / "_embed"  # noqa:PLW2901
            if p.exists():
                libp.append(p)
            if (p / "lib").exists():
                libp.append(p / "lib")
        libp.append(".frozen")

        self.env = {
            "MICROPYPATH": os.pathsep.join(str(x) for x in (lib, lib2, *libp)),
        }
        self.cwd = root

        with (root / "moat.cfg").open("wb") as f:
            f.write(codec.encode(self.cfg["cfg"]))
        with (root / "moat.state").open("w") as f:
            f.write(self.cfg.get("state", "once"))
        if self.cfg.get("large", True):
            with (root / "moat.lrg").open("wb") as f:
                pass

        rlink(libp[0] / "boot.py", root / "boot.py")
        rlink(libp[0] / "main_unix.py", root / "main.py")
        self.argv = [
            # "strace", "-s300", "-o/tmp/mpy.log",
            pre / "build" / ("mpy-unix" + ("-dup" if dupterm else "")) / "micropython",
            "-e",
        ]

        await super().setup()


# Fake "machine" module

machine = attrdict()


class FakeI2C:
    def __init__(self, c, d, **_):
        self._c = c
        self._d = d


class FakePin:
    def __init__(self, pin, **_):
        self._pin = pin


machine.Pin = FakePin
machine.I2C = FakeI2C
machine.SoftI2C = FakeI2C
