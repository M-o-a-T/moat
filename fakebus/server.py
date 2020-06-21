#
# implements a bus server for our fake bus

import sys
import trio
import asyncclick as click
from subprocess import PIPE

from moatbus.backend.stream import StreamBusHandler
from moatbus.server import Server

@click.command()
async def main():
    try:
        async with await trio.open_process(["bin/fake_serialbus"], stdin=PIPE,stdout=PIPE) as backend:
            backstream = trio.StapledStream(backend.stdin,backend.stdout)

            async with StreamBusHandler(backstream) as sb:
                async with Server(sb) as m:
                    await trio.sleep(1)
                    await m.send(1,2,3,b'456')
                    await trio.sleep(99999)
    except trio.ClosedResourceError:
        print("Closed.", file=sys.stderr)

if __name__ == "__main__":
    main()
