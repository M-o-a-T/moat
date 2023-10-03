
from moat.micro.cmd.stream import StreamCmd
from moat.micro.proto.stream import ProcessBuf

class Process(StreamCmd):
    async def stream(self):
        argv = self.cfg["command"]
        path = self.cfg.get("path")
        if path is None and argv[0][0] == '/':
            path = argv[0]

        proc = ProcessBuf(argv, executable=path, stderr=sys.stderr)
        return await AC_use(console_stack(proc, cfg=self.cfg))
