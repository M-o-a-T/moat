"""Regression test: graceful exit of a single ``announcing(...)`` must signal
DOWN for that path even when the same client has other ongoing announcements,
and even when the Link is still alive.

The moat-link-server's graceful shutdown handler (intercepting SIGTERM)
triggers exactly this code path: ``announcing.__aexit__`` clears the retained
host entry while the Link (and its periodic ping) is still up.  Host
monitors must observe the path-level DOWN.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.broadcast import Broadcaster
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.host import HostList


@pytest.mark.anyio
async def test_announce_path_removal_emits_down(cfg):
    """Graceful exit of one ``announcing(...)`` should be reported as DOWN."""
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})

        watcher = await sf.client()

        down_seen: dict = {}
        up_seen: dict = {}

        def _evt(d: dict, k):
            try:
                return d[k]
            except KeyError:
                d[k] = anyio.Event()
                return d[k]

        # (host_id, path) -> last-seen "ok" boolean.
        hc: dict = {}
        # Per-host id, set of paths we have ever seen for that id.
        seen_paths: dict = {}

        async def host_list_consumer(*, task_status):
            async with HostList(cfg=sf.cfg, link=watcher, broadcaster=Broadcaster(1000)) as mq:
                task_status.started()
                async for h in mq:
                    try:
                        up = h.data.p["up"]
                    except (AttributeError, KeyError):
                        up = None
                    current = set(h.data.h.keys())
                    known = seen_paths.setdefault(h.id, set())
                    # Paths that vanished since the last update count as DOWN
                    for k in known - current:
                        if hc.get((h.id, k), None) is False:
                            continue
                        hc[(h.id, k)] = False
                        _evt(down_seen, k).set()
                    for k, v in h.data.h.items():
                        known.add(k)
                        ok = up if up is not None else v.get("up", False)
                        if hc.get((h.id, k), None) is ok:
                            continue
                        hc[(h.id, k)] = ok
                        if ok:
                            _evt(up_seen, k).set()
                        else:
                            _evt(down_seen, k).set()

        await sf.tg.start(host_list_consumer)

        # One service Link with TWO concurrent announcements.
        # Close the first announcement gracefully and verify the consumer
        # sees DOWN for its path while still seeing UP for the second one.
        async with sf.client_() as svc:
            p_short = P("alpha")
            p_long = P("beta")
            keep_running = anyio.Event()
            done = anyio.Event()

            async def keep_long(*, task_status):
                async with svc.announcing(p_long) as s:
                    s.set()
                    task_status.started()
                    await keep_running.wait()
                done.set()

            await sf.tg.start(keep_long)

            async with svc.announcing(p_short) as s:
                s.set()
                await svc.i_sync()
                # Determine the full announced paths from the consumer state.
                with anyio.fail_after(3):
                    while True:
                        paths = seen_paths.get(svc.id, set())
                        if len(paths) >= 2:
                            break
                        await anyio.sleep(0.05)
                full_short_path = next(p for p in paths if p_short.raw[-1] in p.raw)
                full_long_path = next(p for p in paths if p_long.raw[-1] in p.raw)
                with anyio.fail_after(3):
                    await _evt(up_seen, full_short_path).wait()
                    await _evt(up_seen, full_long_path).wait()

            # `announcing(p_short)` has exited gracefully.  The svc Link is
            # still alive and `announcing(p_long)` is still running.
            with anyio.fail_after(3):
                await _evt(down_seen, full_short_path).wait()

            # The other announcement must still be reported as UP.
            assert hc.get((svc.id, full_long_path), None) is True

            keep_running.set()
            with anyio.fail_after(3):
                await done.wait()
