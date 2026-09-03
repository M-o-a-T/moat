"""
Read data from a file
"""

from __future__ import annotations

import anyio
import sys

from . import BaseLoader


class Loader(BaseLoader):
    """
    Load scheduling data from a file.
    """

    @staticmethod
    async def _file(cfg, key):
        async with await anyio.Path(getattr(cfg.data.file, key)).open("r") as f:
            async for line in f:
                yield float(line.strip())

    @staticmethod
    async def price_buy(cfg, t):
        """
        Read future prices for incoming energy, in $$$/kWh.
        File format: one float per line.

        Config:
            data.file.price_buy: path to the data file.
        """
        t  # noqa:B018 # XXX
        async for x in Loader._file(cfg, "price_buy"):
            yield float(x)

    @staticmethod
    async def price_sell(cfg, t):
        """
        Read future prices for sold energy, in $$$/kWh.
        File format: one float per line.

        Config:
            data.file.price_sell: path to the data file.
        """
        t  # noqa:B018 # XXX
        async for x in Loader._file(cfg, "price_sell"):
            yield float(x)

    @staticmethod
    async def solar(cfg, t):
        """
        Projected solar power, in kW.
        File format: one float per line.

        Config:
            data.file.solar: path to the data file.
        """
        t  # noqa:B018 # XXX
        async for x in Loader._file(cfg, "solar"):
            yield float(x)

    @staticmethod
    async def load(cfg, t):
        """
        Projected local consumption, in kW.
        File format: one float per line.

        Config:
            data.file.load: path to the data file.
        """
        t  # noqa:B018 # XXX
        async for x in Loader._file(cfg, "load"):
            yield float(x)

    @staticmethod
    async def soc(cfg):
        """
        The battery's SoC at the start of a simulation.

        File format: one float.

        Config:
            data.file.soc: path to the file.
        """
        async for x in Loader._file(cfg, "soc"):
            return float(x)

    @staticmethod
    async def result(cfg, **kw):
        """
        Send the result data to a file.

        Config:
            data.result.format: yaml, json, or msgpack
        """
        f = cfg.data.format.result
        if f == "yaml":
            from moat.util import yformat  # noqa: PLC0415

            async with await anyio.Path(cfg.data.file.result).open("w") as f:
                await f.write(yformat(kw))

        elif f == "cbor":
            from moat.lib.codec.moat_cbor import Codec as StdCBOR  # noqa: PLC0415

            packer = StdCBOR().encode
            async with await anyio.Path(cfg.data.file.result).open("wb") as f:
                await f.write(packer(kw))

        elif f == "msgpack":
            from moat.lib.codec.moat_msgpack import Codec as StdMsgpack  # noqa: PLC0415

            packer = StdMsgpack().encode
            async with await anyio.Path(cfg.data.file.result).open("wb") as f:
                await f.write(packer(kw))

        elif f == "json":
            import json  # noqa: PLC0415

            async with await anyio.Path(cfg.data.file.result).open("w") as f:
                await f.write(json.dumps(kw))

        else:
            print(f"Unknown output format {f!r}. Use yaml/msgpack/json.")
            sys.exit(1)

    @staticmethod
    async def results(cfg, it):
        """
        Send the resulting data to a file, as a sequence.

        Accepts an asynchronous iterator of per-period result mappings and
        serializes the whole trajectory to ``data.file.results``.

        Args:
            cfg: The scheduler configuration.
            it: An async iterator yielding one result mapping per period.

        Config:
            data.file.results: path to the output file.
            data.format.results: ``yaml``, ``json``, ``cbor``, or ``msgpack``.
        """
        fmt = cfg.data.format.results
        dest = cfg.data.file.results
        if fmt == "yaml":
            from moat.util import yformat  # noqa: PLC0415

            async with await anyio.Path(dest).open("w") as f:
                async for kw in it:
                    await f.write(yformat([kw]))

        elif fmt == "cbor":
            res = []
            async for kw in it:
                res.append(kw)
            from moat.lib.codec.moat_cbor import Codec as StdCBOR  # noqa: PLC0415

            packer = StdCBOR().encode

            async with await anyio.Path(dest).open("wb") as f:
                await f.write(packer(res))

        elif fmt == "msgpack":
            res = []
            async for kw in it:
                res.append(kw)
            from moat.lib.codec.moat_msgpack import Codec as StdMsgpack  # noqa: PLC0415

            packer = StdMsgpack().encode

            async with await anyio.Path(dest).open("wb") as f:
                await f.write(packer(res))

        elif fmt == "json":
            import json  # noqa: PLC0415

            res = []
            async for kw in it:
                res.append(kw)
            async with await anyio.Path(dest).open("w") as f:
                await f.write(json.dumps(res))

        else:
            print(f"Unknown output format {fmt!r}. Use yaml/json/cbor/msgpack.")
            sys.exit(1)
