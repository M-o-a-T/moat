"""
This module implements an XKNX client, connecting to a local knx daemon
(not discoverable, on localhost, not talking to any other KNX stuff you
might have running).

This code is here for support of testing. It does not talk to MoaT-KV.
See ``tests/test_basic.py`` for code that does.

"""

from __future__ import annotations

import anyio
import os
import tempfile
from contextlib import asynccontextmanager

import xknx
from xknx.devices import BinarySensor, ExposeSensor, Sensor, Switch
from xknx.io import ConnectionConfig, ConnectionType


class Tester:  # noqa:D101
    _client = None
    _server = None
    _socket = None

    def __init__(self, port):
        self.TCP_PORT = port

    @asynccontextmanager
    async def _daemon(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "test.ini")
            self._socket = os.path.join(d, "test.sock")
            with open(cfg, "w") as f:  # noqa:ASYNC230
                # The TCP server is here just to signal something like readiness
                print(
                    f"""\
[main]
addr = 0.0.1
client-addrs = 0.0.2:3
connections = server,A.tcp
#debug = debug-all
#filters = log

[B.log]
filter = log

[A.tcp]
port = {self.TCP_PORT}
server = knxd_tcp
systemd-ignore = false
#filters = log

[server]
server = ets_router
tunnel = tunnel
port = {self.TCP_PORT}
discover = false

[tunnel]
filters = B.log
#debug = debug-all

[debug-all]
trace-mask = 0x3ff

""",
                    file=f,
                )
            proc = await anyio.open_process(["knxd", cfg])
            try:
                with anyio.fail_after(10):
                    while True:
                        try:
                            s = await anyio.connect_tcp("127.0.0.1", self.TCP_PORT)
                            await s.aclose()
                            break
                        except OSError:
                            await anyio.sleep(0.1)
                await anyio.sleep(0.2)
                yield proc
            finally:
                proc.terminate()
                with anyio.move_on_after(2) as cs:
                    cs.shield = True
                    await proc.wait()
                proc.kill()

    @asynccontextmanager
    async def run(self):  # noqa:D102
        ccfg = ConnectionConfig(
            connection_type=ConnectionType.TUNNELING,
            gateway_ip="127.0.0.1",
            gateway_port=self.TCP_PORT,
        )
        async with (
            self._daemon() as server,
            xknx.XKNX().run(connection_config=ccfg) as client,
        ):
            self._server = server
            self._client = client
            yield self

    def switch(self, *a, **k):  # noqa:D102
        res = Switch(self._client, *a, **k)
        self._client.devices.add(res)
        return res

    def binary_sensor(self, *a, **k):  # noqa:D102
        res = BinarySensor(self._client, *a, **k)
        self._client.devices.add(res)
        return res

    def sensor(self, *a, **k):  # noqa:D102
        res = Sensor(self._client, *a, **k)
        self._client.devices.add(res)
        return res

    def exposed_sensor(self, *a, **k):  # noqa:D102
        res = ExposeSensor(self._client, *a, **k)
        self._client.devices.add(res)
        return res
