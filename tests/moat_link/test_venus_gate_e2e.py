"""End-to-end test for the Venus gateway against a real Venus OS device.

Set ``VENUS_HOST`` (and optionally ``VENUS_PASSWORD``) to enable.

The test:

1. Probes the Venus broker for its retained ``N/+/system/+/Serial`` topic
   to discover the portal ID.
2. Spins up a local MoaT-Link server + client backed by an ephemeral
   FlashMQ broker.
3. Stores a Venus gate descriptor and runs the gate.
4. Waits until ``DEST.settings.0.Settings.Gui2.OnBoarding`` has been
   synchronised from Venus and equals ``2``.
"""

from __future__ import annotations

import anyio
import logging
import os
import pytest

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.backend import get_backend
from moat.link.gate import run_gate

VENUS_HOST: str | None = os.environ.get("VENUS_HOST")
VENUS_PASSWORD: str | None = os.environ.get("VENUS_PASSWORD")

#: Where to mount the Venus subtree inside MoaT-Link.
DEST = P("venus")

#: Path of the value we expect the gate to import from Venus.
TARGET = DEST + P("settings.0.Settings.Gui2.OnBoarding")

#: Expected value at ``TARGET`` once the gate has finished syncing.
EXPECTED_VALUE = 2

#: Name of the codec-vector tree used by the Venus gate in this test.
CODEC_VEC = "venustest"

#: Topic substring used to recognise the no-op battery debug values
#: that the gate is configured to drop via the null codec.
DROPPED_TOPIC_LEAF = "ChargeModeDebugFloat"


class _RecordingHandler(logging.Handler):
    """Collect emitted log records for later inspection."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _venus_backend_cfg() -> attrdict:
    """Build a backend config for connecting to the real Venus broker."""
    cfg = attrdict(
        driver="mqtt",
        codec="json",
        host=VENUS_HOST,
        port=1883,
        keep_alive=60,
    )
    if VENUS_PASSWORD:
        cfg.username = "victron"
        cfg.password = VENUS_PASSWORD
    return cfg


async def _discover_portal_id() -> str:
    """Return the Venus portal ID, read from the retained ``Serial`` topic."""
    async with (
        get_backend(
            {"backend": _venus_backend_cfg()},
            name="venus_probe",
        ) as bk,
        bk.monitor(P("N"), subtree=True, codec="noop") as mon,
    ):
        with anyio.fail_after(15):
            async for msg in mon:
                t = msg.topic
                # N/<portal>/system/<inst>/Serial
                if len(t) >= 5 and t[0] == "N" and t[2] == "system" and t[-1] == "Serial":
                    return t[1]
    raise AssertionError("Venus monitor ended without a Serial message")


@pytest.mark.skipif(not VENUS_HOST, reason="VENUS_HOST not set")
@pytest.mark.anyio
async def test_venus_gateway_e2e(cfg) -> None:
    """Verify that the Venus gate mirrors a known Venus value into MoaT-Link."""
    portal_id = await _discover_portal_id()

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init="TEST")
        client = await sf.client()

        # Configure a codec-vector tree that marks the noisy Venus
        # ``battery/*/Info/ChargeModeDebugFloat`` payloads (which carry
        # values such as ``NaN`` that can't survive a UTF-8 round-trip)
        # as belonging to the null codec, so the gate drops them.
        await client.d_set(
            P("conv") + P(CODEC_VEC) + P(f"battery.+.Info.{DROPPED_TOPIC_LEAF}"),
            {"codec": "null"},
        )

        gate_path = P("gate.venustest")
        await client.d_set(
            gate_path,
            {
                "driver": "venus",
                "src": DEST,
                "dst": P(portal_id),
                "codec": P(CODEC_VEC),
                "backend": dict(_venus_backend_cfg()),
                "timeout": 60,
            },
        )
        # ``d_set`` posts via MQTT and returns before the server has
        # processed the message; sync explicitly so ``run_gate`` finds the
        # config when it does ``d_get``.
        await client.i_sync()

        handler = _RecordingHandler()
        backend_logger = logging.getLogger("moat.link.backend")
        backend_logger.addHandler(handler)
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(run_gate, sf.cfg, client, gate_path)

                with anyio.fail_after(90):
                    async with client.d_watch(TARGET, state=None) as mon:
                        async for val in mon:
                            assert val == EXPECTED_VALUE
                            break

                tg.cancel_scope.cancel()
        finally:
            backend_logger.removeHandler(handler)

        # The null-codec placeholder must have prevented the gate from
        # mirroring the offending Venus payloads into MoaT-Link, so the
        # link backend never had to drop them on the outgoing side.
        offenders = [
            r
            for r in handler.records
            if r.getMessage().startswith("Dropping non-UTF8 payload")
            and DROPPED_TOPIC_LEAF in r.getMessage()
        ]
        assert offenders == [], offenders
