from moat.micro.cmd.stream import BaseCmdMsg
from moat.micro.proto.stream import ProcessBuf


class Process(BaseCmdMsg):
    argv = None
    path = None

    async def stream(self):
        argv = self.cfg["command"] if self.argv is None else self.argv
        path = self.cfg.get("path") if self.path is None else self.path
        if path is None and argv[0][0] == '/':
            path = argv[0]

        proc = ProcessBuf(argv, executable=path, stderr=sys.stderr)
        return await AC_use(console_stack(proc, cfg=self.cfg))
