# Plan: End-to-End Test for moat-link Server-to-Server Synchronisation

File: `tests/moat_link/test_sync.py`

## Architecture Overview

```
  [Master FlashMQ :Mport]
       /           \
  bridge           bridge
(pub/sub #2)   (pub/sub #2)
     /               \
[Sat1 FlashMQ :S1]  [Sat2 FlashMQ :S2]
        |                    |
  [moat-link Srv1]    [moat-link Srv2]
    name="LS1"           name="LS2"
    TCP :P1              TCP :P2
        |
  [Gate "test_gate"
   driver=link, server="LS2"
   src=:R, delay=0.1s]
   (started later)
```

Through the MQTT bridges, LS1 and LS2 share the same logical MQTT namespace and discover each other's server announcements (`run.service.main.server/{name}`). They set up direct TCP links via `_watch_up`.

When the master is killed the two satellites are isolated, but each still holds the other's retained server announcement in its own broker memory (it was delivered before the split). The gate can therefore still open a direct TCP connection to LS2.

---

## Critical: remote Link must use Sat2's MQTT, not Sat1's

The `Link` client uses its MQTT backend for two things that are coupled to
which broker it talks to:

1. **Client ping** – the client publishes `run.ping.id/{id}` on its MQTT
   backend. The *server* monitors that very same `run.ping.id/*` subtopic on
   *its* MQTT broker (`_monitor_pings`). If the remote Link uses Sat1's MQTT
   but LS2 is on Sat2's MQTT, LS2 never sees the client's pings and evicts
   the connection.

2. **Auth token freshness** – the server announcement on MQTT
   (`run.service.main.server/{name}`) carries the current auth token. After
   the master dies the retained copy on Sat1 is frozen at the pre-split token;
   if LS2 has since called `refresh_auth` (e.g. via the actor-ping cycle)
   the old token may no longer be accepted.

Therefore the gate's *remote* `Link` must be created with **cfg2** (backend
pointing at Sat2), not cfg1.  The current `gate/link.py` hard-codes
`self.link.link.cfg` (the local config). That code needs a small change: if
the gate config contains a `backend` dict, use it to override the backend when
building the remote `Link`.

---

## Infrastructure helpers

### `run_bridge_broker(master_port, *, task_status)`

Starts a FlashMQ instance with a bridge to the master (or to another satellite later).  Returns `(sat_port, process, config_path)` via `task_status`.

```
allow_anonymous true
retained_messages_mode enabled_without_persistence
thread_count 1
log_level warning

listen {
    protocol mqtt
    port {sat_port}
    inet4_bind_address 127.0.0.1
}

bridge {
    address 127.0.0.1
    port    {master_port}
    publish   # 2
    subscribe # 2
    bridge_protocol_bit false
}
```

Use `anyio.open_process(["flashmq", "-c", str(config_path)], ...)` (not `run_process`) so we have a handle to the process object and can:
- read its PID for later SIGHUP
- cancel/kill it cleanly

Wait for the port to accept a TCP connection before signalling `task_status.started(...)`.

### `run_master_broker(*, task_status)`

Like the existing `run_broker` in `_test.py` but without a bridge block.  Returns just `master_port`.

### `make_sat_cfg(base_cfg, sat_port)`

Returns a copy of the base moat-link config with `backend.port = sat_port`.

### `reload_bridge(process, config_path, new_bridge_port)`

Rewrites the FlashMQ config for satellite 1 to point the bridge at the new port (satellite 2 instead of master), then sends `signal.SIGHUP` to the process. Waits a short time for the bridge to reconnect.

```python
import os, signal

await config_path.write_text(make_config(sat_port, new_bridge_port))
os.kill(process.pid, signal.SIGHUP)
await anyio.sleep(0.3)  # give bridge time to reconnect
```

---

## Test function: `test_server_sync`

Mark: `@pytest.mark.anyio`

### Phase 0 – Startup

```
async with anyio.create_task_group() as tg:
    master_port = await tg.start(run_master_broker)
    s1_port, s1_proc, s1_cfg = await tg.start(run_bridge_broker, master_port)
    s2_port, s2_proc, s2_cfg = await tg.start(run_bridge_broker, master_port)

    cfg1 = make_sat_cfg(cfg, s1_port)
    cfg2 = make_sat_cfg(cfg, s2_port)

    srv1 = Server(cfg1, "LS1", init="sync-test")
    srv2 = Server(cfg2, "LS2")
    await tg.start(srv1.serve)
    await tg.start(srv2.serve)

    # Give the bridges and server-to-server TCP links time to settle
    await anyio.sleep(0.5)
```

Both servers share the same MQTT namespace through the bridges and will discover each other via `_watch_up`.

### Phase 1 – Normal sync (master alive)

Open one client on each server:

```python
async with Link(cfg1, "C1") as c1, Link(cfg2, "C2") as c2:
    ...
```

Set a few data items via `c1.d_set(P("data.x"), 1)`.
Watch on `c2.d_watch(P("data"), subtree=True)` and assert the values arrive (with `anyio.fail_after(2)`).

Repeat the other direction (c2 → c1).

### Phase 2 – Network split (master killed)

```python
s1_proc.terminate()  # or .kill() — this is the *master* process
await anyio.sleep(0.3)
```

Set items on each side:
- `c1.d_set(P("data.split_a"), 10)`
- `c2.d_set(P("data.split_b"), 20)`

Verify **neither** appears on the opposite server (short timeout that is expected to expire).

### Phase 3 – Gate reconnects the islands

Store the gate config in LS1's data tree. Include the **Sat2 backend address**
so the remote `Link` connects to the correct MQTT broker:

```python
await c1.d_set(
    P("gate.test_gate"),
    {
        "driver": "link",
        "src": Root.get(),  # sync the whole root
        "server": "LS2",
        "delay": 0.1,
        "name": "test_gate",
        # ← tells gate/link.py which MQTT broker to use for the remote Link
        "backend": {"host": "127.0.0.1", "port": s2_port},
    },
)
```

Run the gate as a background task:

```python
from moat.link.gate import run_gate

gate_cs = anyio.CancelScope()


async def run_the_gate():
    with gate_cs:
        await run_gate(cfg1, c1, P("gate.test_gate"))


tg.start_soon(run_the_gate)
await anyio.sleep(0.5)  # wait for gate sync to finish
```

Assert that:
- `c2.d_get(P("data.split_a"))` == 10
- `c1.d_get(P("data.split_b"))` == 20

### Phase 4 – Direct bridge + dedup check

Reconfigure satellite 1 to bridge directly to satellite 2:

```python
await reload_bridge(s1_proc, s1_cfg, s2_port)
```

Set up a raw MQTT counter on one path. Use a `Backend` monitor on satellite 1 watching the specific topic:

```python
updates: list[Any] = []


async def count_updates():
    async with get_backend(cfg1) as bk:
        async with bk.monitor(P("data.dedup"), subtree=False) as mon:
            async for msg in mon:
                updates.append(msg.data)


tg.start_soon(count_updates)
```

Now update via `c1`:
```python
await c1.d_set(P("data.dedup"), 42)
await anyio.sleep(0.3)  # longer than gate delay=0.1
```

Assert:
1. `c2.d_get(P("data.dedup"))` == 42  (data arrived on server 2)
2. `len(updates) == 1`  (exactly one MQTT publish on the topic — gate delayed and cancelled its forward because the bridge got there first)

Do a few more updates and verify the count each time.

Cancel the gate and counter tasks, cancel the whole task group.

---

## Implementation Notes

### Required code change in `gate/link.py`

The current `run_` method creates the remote Link with the local config:

```python
async with Link(self.link.link.cfg, only=server_name) as remote:
```

This must be extended to honour a `backend` override from the gate config:

```python
async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
    server_name = self.cf.get("server")
    if not server_name:
        raise ValueError("Link gate requires 'server' configuration")

    cfg = self.link.link.cfg
    if "backend" in self.cf:
        # Deep-merge: gate's backend overrides local backend settings.
        cfg = combine_dict({"backend": dict(self.cf.backend)}, cfg, cls=attrdict)

    async with Link(cfg, only=server_name) as remote:
        self._remote = remote
        await super().run_(task_status=task_status)
```

The test gate config passes `backend.port = s2_port` so the remote Link
publishes pings on Sat2 (where LS2 is listening) and reads LS2's fresh
server announcement.

### Config for two separate servers

The two moat-link servers need truly separate configs (different `backend.port`). The easiest approach is to deep-copy the base `cfg` fixture and set `cfg.link.backend.port = satN_port` for each. The `root` should be the same for both so they share the same MQTT namespace (which is the point of the bridge).

### Waiting for gate to finish initial sync

`run_gate` calls `gate.run()` which calls `run_()` which signals `task_status.started()` only after the initial dual scan. Use `tg.start(run_the_gate)` instead of `tg.start_soon` so we block until the gate reports ready.

### Server discovery across the bridge

After the bridge connects, the servers' retained announcements propagate. There may be a short delay before `_watch_up` picks up the other server. A 0.5 s sleep after startup is conservative but safe for a test. If fragile, add an explicit poll of `c1.d_get(P(":R.run.service.main.server.LS2"))`.

### MQTT loop detection in bridges

FlashMQ bridges have built-in loop detection (they don't re-send messages they received from a bridge back out on the same bridge). This means a message set via c1 traverses: Sat1 → Sat2 (bridge). If the gate also tries to forward it, it arrives at Sat2 again — but since the topic's retained value is already identical, it's a no-op at the server level. However, at the MQTT level it's still a second publish. The gate's 0.1 s delay + cancellation upon seeing the bridge-forwarded echo is the mechanism that prevents this second publish.

### SIGHUP and `anyio.open_process`

`anyio.open_process` returns an `anyio.abc.Process`. Its `.pid` attribute gives the PID. Use `os.kill(pid, signal.SIGHUP)` (not async — that's fine for a signal send).

Cleanup: use `process.terminate()` / `process.wait()` inside a `CancelScope(shield=True)` to avoid leaving zombie processes.

### Gate config path

The gate path in moat-link is `gate/test_gate`. `run_gate` takes either a `Path` or a string. The gate reads its own config from `link.d_get(path)` and then imports `moat.link.gate.link.Gate`.

### Root path

Both servers must use the same `cfg.link.root`. The existing Scaffold sets `Root.set(cfg.root)` in `_ctx`. For this test we do the same manually, or we can wrap the whole thing in a modified Scaffold-like helper. The root needs to be something test-specific, e.g. `!P test.sync` injected into both configs.

---

## Open Questions / Follow-up Issues

1. **Bridge echo timing**: The test assumes the bridge is faster than 0.1 s (the gate delay). On a loaded CI machine this might be flaky. The gate delay could be made configurable per-test and set to 0.5 s with the bridge given 0.3 s.

2. **`only=` with a stopped master**: The gate's remote Link now uses Sat2's MQTT. LS2's own retained announcement is always fresh on Sat2, so the TCP address and auth token are current regardless of the master's status.

3. **Multiple gate instances**: The `run_gate` `_restart` loop restarts when the gate config changes. Tests that modify the gate config must be aware of this.

4. **Test isolation**: Since all three brokers use ephemeral ports and in-memory retained messages, tests don't pollute each other. But the global `Root` context variable must be reset (already handled by `clear_root` fixture).

5. **`retain_messages_mode`**: FlashMQ is started with `enabled_without_persistence` — retained messages live only in memory and are lost if the broker restarts. This is the correct behaviour for a test: no leftover state between runs.
