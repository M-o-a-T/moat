# Testing MoaT.micro

## In-process (CPython) testing

The fastest and most portable way to test a MoaT-micro app is to run the
entire stack inside the test process using `mpy_stack`.  No MicroPython
binary is needed; everything executes under CPython with anyio as the
scheduler.

### Setup

```python
import pytest
from moat.lib.micro import sleep_ms
from moat.lib.path import P
from moat.micro._test import mpy_stack

CFG = """
app: dir
myapp:
  app: part.SomeApp
  pin: !P pin
  # ...further config...
pin:
  app: _fake.Pin
  pin: X
"""

@pytest.mark.anyio
async def test_something(tmp_path):
    async with mpy_stack(tmp_path, CFG) as d:
        app = d.sub_at(P("myapp"))
        pin = d.sub_at(P("pin"))
        # ...
```

`mpy_stack` accepts either a YAML string (used above) or an `attrdict`
already parsed from YAML.  The `tmp_path` fixture provides the working
directory for the stack.

### Configuration format

The top-level key must be `app: dir` (a `Dispatcher`).  Named sub-keys
are sub-apps, each with their own `app:` field and whatever configuration
the app requires.

#### App naming

App class names map to `moat.micro.app.<name>` on CPython:

| YAML `app:` value | Python module |
|---|---|
| `part.PWM` | `moat.micro.app.part` → lazy-loads `moat.micro.part.pwm.PWM` |
| `part.Relay` | `moat.micro.app.part` → `moat.micro.part.relay.Relay` |
| `_fake.Pin` | `moat.micro.app._fake.Pin` |
| `_fake.ADC` | `moat.micro.app._fake.ADC` |
| `_test.Cmd` | `moat.micro.app._test.Cmd` |
| `dir` | built-in dispatcher |

The `part.*` names go through a lazy-loader in `moat/micro/app/part.py`;
see that file for the full list.

#### Path references between apps

Use the `!P` YAML tag to create a `moat.lib.path.Path` that points to
another app in the hierarchy:

```yaml
pin: !P pin          # refers to the top-level "pin" sub-app
sensor: !P sensors.t # refers to d["sensors"]["t"]
```

Apps resolve these paths at setup time via `self.root.sub_at(path)`.

### Calling commands from tests

`d.sub_at(P("name"))` returns a lightweight proxy.  Calling a method on
it dispatches to the matching command on the app:

| Proxy call | App method invoked |
|---|---|
| `await proxy.r()` | `cmd_r(self)` |
| `await proxy.w(val)` | `cmd_w(self, val)` or `stream_w(self, msg)` |
| `await proxy.s()` | `cmd_s(self)` |
| `await proxy(val)` | `cmd(self, val)` — the default/SDP command |
| `await proxy()` | `cmd(self)` — read variant of SDP |

Positional arguments become `msg[0]`, `msg[1]`, …; keyword arguments
become `msg["key"]`.

### Startup and readiness

Each app's lifecycle is: `setup()` → `task()`.  `task()` calls
`self.set_ready()` (via `if L: self.set_ready()`) as its first action.

The proxy **blocks until the app is ready** before dispatching any
command.  This means you can call commands immediately after
`mpy_stack` yields the stack; no explicit `wait_ready` call is needed.

### Fake hardware

#### `_fake.Pin`

A software pin that can be read and written from both sides.

```yaml
pin:
  app: _fake.Pin
  pin: X        # arbitrary label; only used as a dict key in PINS
  init: false   # optional initial value (default False)
```

From the test:
- `await pin()` → returns the current boolean value.
- `await pin(True)` → sets the pin to `True`.

From inside an app (e.g. PWM, Relay), the same object is used via
`self.root.sub_at(cfg["pin"])`.  When the app writes `await self.pin(True)`,
the value is visible immediately to the test via `await pin()`.

#### `_fake.ADC`

A random-walk ADC that drifts between `min` and `max`.

```yaml
adc:
  app: _fake.ADC
  min: 0.0
  max: 1.0
  step: 0.1   # max per-sample step
  seed: 42    # optional, for reproducibility
```

Call `await adc.r()` to get the next value.

### Timing

`sleep_ms(n)` is a real wall-clock sleep (`anyio.sleep(n/1000)`).  All
app tasks run concurrently in the same anyio event loop as the test.
Every `await` in the test yields to the scheduler, allowing pending app
tasks to run.

**Any `await` point between two assertions is sufficient for the app to
make one scheduler pass.**  A short `await sleep_ms(5)` is enough to
let an app react to an event that was just set; there is no need for
`asyncio.sleep(0)` or similar tricks.

#### Anchoring time-driven tests

Many apps keep a `t_last` timestamp that is set when the app's `task()`
starts (or when the output last changed state).  Subsequent timing
decisions — "has enough time elapsed to switch?" — are taken relative to
`t_last`.

A reliable pattern for testing timed transitions:

1. **Anchor in a known state** by calling a command that puts the app
   into a stable resting condition (e.g. `val=0` for always-off).
2. **Wait long enough** that `t_last` is guaranteed to be older than the
   longest `t_off`/`t_on`/`min` you will test next.  A sleep of
   `max(t_off, min) * 1.5` is a safe margin.
3. **Trigger the transition** and check state after a short sleep.

Without step 2, an app waiting for an event may not fire immediately
after you change its target value, because its internal check
`td >= t_off` is still `False`.

Example:

```python
# Anchor: always-off, wait 200 ms so td >> t_off=150 ms
await app.w(0)
await sleep_ms(200)
assert await pin() is False

# Now switching to val=25 (t_off=150 ms) fires the wakeup event at once.
await app.w(25)
await sleep_ms(20)       # one scheduler pass to let the app switch
assert await pin() is True
```



## Unix MicroPython

Setting the LOG_BRK envvar to 1 forces a breakpoint when logging an
error.

### Running tests

The standard test suite includes MicroPython tests. No further action is
required, other than building the Unix port of MicroPython in the first
place.

### Test infrastructure

#### Test commands

##### \_test.MpyCmd

The `_test.MpyCmd` app starts a locally-built MicroPython subprocess and
runs a MoaT link to its stdin/stdout.

Its MoaT system uses the app's `cfg` config value as its configuration.

##### \_test.MpyRaw

Likewise but stdio is exported as a bytestream.

##### Loop

A loopback link.

Messages are MsgPack-encoded (and immediately decoded again of course).
Note however that both sides use the same Proxy cache, thus this link
exercises encoding of proxied classes, but random objects are still
passed transparently.

###### echo

Returns a map with the member `r` that replicates its `m` argument.

## Real satellites

Regular tests with real satellites are difficult because their flash
storage only supports a limited number of write cycles.

Nevertheless, we do support testing on modules where either enough RAM
is available (ESP32 with external SPI SRAM), or for additional testing
for releases (RP2040). Both require additional connections to their boot
and reset inputs.

MoaT hardware designs support this with an USB plug with external power
control inputs, as well as a small hub that includes a GPIO chip if the
test host doesn't supply 3.3V pins.
