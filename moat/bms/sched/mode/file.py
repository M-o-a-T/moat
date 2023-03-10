import anyio
from . import BaseLoader

class Loader(BaseLoader):
    """
    Load scheduling data from a file.
    """

    @staticmethod
    async def _file(cfg, key):
        async with await anyio.Path(getattr(cfg.data.file,key)).open("r") as f:
            async for line in f:
                yield float(line.strip())

    @staticmethod
    async def price_buy(cfg):
        """
        Read future prices for incoming energy, in $$$/kWh.
        File format: one float per line.

        Config:
            data.file.price_buy: path to the data file.
        """
        async for x in Loader._file(cfg, "price_buy"):
            yield float(x)
        

    @staticmethod
    async def price_sell(cfg):
        """
        Read future prices for sold energy, in $$$/kWh.
        File format: one float per line.

        Config:
            data.file.price_sell: path to the data file.
        """
        async for x in Loader._file(cfg, "price_sell"):
            yield float(x)
        

    @staticmethod
    async def solar(cfg):
        """
        Projected solar power, in kW.
        File format: one float per line.

        Config:
            data.file.solar: path to the data file.
        """
        async for x in Loader._file(cfg, "solar"):
            yield float(x)


    @staticmethod
    async def load(cfg):
        """
        Projected local consumption, in kW.
        File format: one float per line.

        Config:
            data.file.load: path to the data file.
        """
        async for x in Loader._file(cfg, "solar"):
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
    async def result(cfg, kw):
        """
        Send the result data to a file.

        Config:
            data.stdout.format: yaml, json, or msgpack
        """
        f = cfg.data.format.result
        if f == "yaml":
            from moat.util import yformat
            async with await anyio.Path(cfg.data.file.result).open("w") as f:
                await f.write(yformat(kw))
        elif f == "msgpack":
            from moat.util import packer
            async with await anyio.Path(cfg.data.file.result).open("wb") as f:
                await f.write(packer(kw))
        elif f == "json":
            import json
            async with await anyio.Path(cfg.data.file.result).open("w") as f:
                await f.write(json.dumps(kw))
        else:
            print(f"Unknown output format {f !r}. Use yaml/msgpack/json.")
            sys.exit(1)


    @staticmethod
    async def results(cfg, it):
        """
        Print the resulting data, as a YAML array.

        Config:
            data.stdout.format: yaml, json, or msgpack
        """
        f = cfg.data.format.results
        if f == "yaml":
            from moat.util import yformat
            async with await anyio.Path(cfg.data.file.result).open("w") as f:
                async for kw in it:
                    await f.write(yformat([kw]))
        elif f == "msgpack":
            res = []
            async for kw in it:
                res.append(kw)
            from moat.util import packer
            async with await anyio.Path(cfg.data.file.result).open("wb") as f:
                await f.write(packer(res))
        elif f == "json":
            import json
            async for kw in it:
                res.append(kw)
            async with await anyio.Path(cfg.data.file.result).open("w") as f:
                await f.write(json.dumps(res))
        else:
            print(f"Unknown output format {f !r}. Use yaml/msgpack/json.")
            sys.exit(1)

