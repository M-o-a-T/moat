import anyio

from contextlib import asynccontextmanager
from moat.micro.cmd import StreamCmd

class Process(StreamCmd):
    def conn(self):
        argv = self.cfg["command"]
        path = self.cfg.get("path", argv[0])
        return self._conn(path, argv)

    @asynccontextmanager
    async def _conn(self, argv):
        async with await anyio.open_process(argv, stderr=sys.stderr) as proc:
            ser = anyio.streams.stapled.StapledByteStream(proc.stdin, proc.stdout)
            async with get_link_serial(ser, self.cfg["link"]) as link:
                yield link

class TestProcess(Process):
    @asynccontextmanager
    async def conn(self):
        try:
            os.stat("micro/lib")
        except OSError:
            pre = Path(__file__).parents[2]
        else:
            pre = "micro/"

        root = temp / "root"
        try:
            root.mkdir()
            (root / "tests").symlink_to(Path("tests").absolute())
        except EnvironmentError:
            pass
        with (root / "moat.cfg").open("wb") as f:
            f.write(packer(cfg))

        argv = [
            # "strace","-s300","-o/tmp/bla",
            pre / "lib/micropython/ports/unix/build-standard/micropython",
            pre / "tests-mpy/mplex.py",
            str(root),
            str(pre),
        ]
