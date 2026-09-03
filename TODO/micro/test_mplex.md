# Test Plan: MPlex (Multiplexed I/O Part)

## Background

`moat/micro/part/mplex.py` wraps `support/mplex.py` as a `BaseCmd` RPC
part. It scans a matrix of buttons/LEDs using hardware timer-driven
row selection:

- **Scan pins** select rows in rotation (hardware timer, periodic).
- **Input pins** read the currently-selected row → button state bitmap.
- **Output pins** drive the currently-selected row → LED state bitmap.
- Input changes are collected as `(button, pressed)` tuples and streamed
  via an RPC streaming command (`stream_i`).
- Output bits are read/written via `cmd_o` / `cmd_w`.
- Input bits are read via `cmd_r`.

The module is **MicroPython-only**: it imports `machine.Pin`,
`machine.Timer`, and `micropython.disable_irq` / `enable_irq`.
It lives in `moat/micro/_embed/lib/` which is excluded from CPython
imports and `ty` type-checking.

## Challenge

The part cannot be imported in CPython due to `from machine import Pin,
Timer` and `from micropython import const, disable_irq, enable_irq`.
Two complementary testing strategies cover different layers:

### Strategy 1: CPython unit tests with mocked `machine` (pure logic)

**Goal:** Exercise the scanning algorithm, bitmask manipulation, and
change-tracking logic without real hardware or MicroPython.

**Approach:** Inject fake `machine.Pin`, `machine.Timer`, and
`micropython` modules into `sys.modules` before importing `mplex.py`,
then instantiate `MPlex` with controlled fake-pin values.

This mirrors the existing `moat/micro/_test.py` pattern (`FakePin`,
`machine = attrdict()`) but extends it with:

- **`FakePin`** that records its mode/value and can be externally set
  (so tests simulate button presses).
- **`FakeTimer`** that stores `callback` / `period` and can be manually
  triggered (calling `callback(timer)`) instead of firing on real IRQ.
- **`micropython` stub** providing `const(lambda x: x)`,
  `disable_irq()` → sentinel, `enable_irq(state)` → noop.

Since `MPlex.__init__` calls `Pin(pinnum, mode=..., value=...)` and
stores the resulting objects, and `step()` calls `pin()` to read and
`pin(value)` to write, the fake pins must support both call-as-getter
and call-as-setter semantics.

#### Test cases (unit):

1. **`test_init_basic`** — Construct MPlex with 2 scan, 3 input, 2 output
   pins. Assert `len(scan)==2`, `len(input)==3`, `len(output)==2`,
   `state==0`, `changed==0`, `out==0`, `this is None` (not started).

2. **`test_init_empty_inputs`** — Zero input pins. Construction succeeds;
   `step()` runs without error (no input reading). `_drain_changes()`
   yields nothing.

3. **`test_init_empty_outputs`** — Zero output pins. Construction succeeds;
   `step()` skips output driving.

4. **`test_start_stop`** — Call `_start_scan()`: asserts `this==0`,
   `imask==omask==1`, timer initialized. Calling `_start_scan()` again
   raises `RuntimeError("already running")`. Call `_stop_scan()`:
   `this is None`, timer deinited, all output/scan pins de-asserted.

5. **`test_step_advances_scan_position`** — With 3 scan pins, call
   `step()` 3 times. Assert `this` cycles 0→1→2→0 and masks reset to 1
   on wrap-around.

6. **`test_step_reads_input_change`** — Set a fake input pin to active.
   Call `step()`. Assert `self.state` has the corresponding bit set and
   `self.changed` marks it. `self.work` flag is set.

7. **`test_step_no_change_no_flag`** — Input pin stays the same across
   `step()`. `self.changed` stays 0, `self.work` not set.

8. **`test_drain_changes`** — Simulate multiple input changes, then call
   `_drain_changes()`. Assert yielded `(btn, pressed)` tuples match
   expected indices and states. Assert `changed` cleared afterward.

9. **`test_get_in_set_out_get_out`** — `set_out(5, True)` →
   `get_out(5) is True`, `get_out(4) is False`. `get_in(3)` reads from
   `self.state` bitmask.

10. **`test_inversion_flags`** — With `inv=dict(scan=True, input=True,
    output=True)`, active-low pins flip the polarity: a pin reading
    `True` (inactive-high) is interpreted as "pressed" when `vi=True`.

11. **`test_step_drives_output_pins`** — `set_out(bit, True)`, advance
    scan to the row covering that bit, call `step()`. Assert the
    corresponding fake output pin was driven to the active value.

12. **`test_double_start_raises`** — `_start_scan()` then `_start_scan()`
    → `RuntimeError`.

13. **`test_stop_when_not_running`** — `_stop_scan()` without prior
    `_start_scan()` → no error (early-return guard).

14. **`test_disable_enable_irq_in_drain`** — Verify `_drain_changes()`
    calls `disable_irq`/`enable_irq` around each bit-clear (the fake
    micropython stub records call sequences).

#### Implementation notes for unit tests:

```python
import sys, types

# Stub micropython module
mp = types.ModuleType("micropython")
mp.const = lambda x: x
_irq_depth = []
mp.disable_irq = lambda: (_irq_depth.append(1), 0)[1]
mp.enable_irq = lambda s: _irq_depth.pop() if _irq_depth else None
sys.modules["micropython"] = mp

# Stub machine module
machine = types.ModuleType("machine")
machine.Pin = FakePin
machine.Timer = FakeTimer
machine.Pin.OUT = 1
machine.Pin.IN = 0
machine.Timer.PERIODIC = 1
sys.modules["machine"] = machine
```

`FakePin` needs:
- `__init__(self, pin_num, mode=IN, value=0)` storing mode, _value.
- `__call__(self, value=_SENTINEL)` — getter if no arg, setter if arg.
- External hook to simulate input: `pin.simulate(new_val)`.

`FakeTimer` needs:
- `__init__(self, timer_id)`.
- `init(mode, period, callback, hard)` storing params.
- `deinit()` clearing.
- `tick()` calling `self.callback(self)` for manual stepping.

Import path: the part lives in `_embed/lib/moat/micro/part/mplex.py`.
Tests can import it by temporarily adjusting `sys.path` to include the
`_embed/lib` directory, or by using `importlib` with the file path.

Alternatively, factor the pure-logic methods into a mixin that doesn't
require `machine` at import time — but that's a refactoring decision
best left to the implementer.

---

### Strategy 2: MicroPython integration tests (real firmware)

**Goal:** End-to-end validation on actual MicroPython, exercising the
hardware timer, real `ThreadSafeFlag`, and RPC streaming.

**Prerequisites:**
- `ext/micropython` populated (`make setup`).
- `mpy-unix` build present (`ext/micropython/build/mpy-unix/micropython`).
- The `MpyBuf` / `_test.MpyCmd` test harness (used by `test_pid.py`,
  `test_mplex.py`).

**Problem:** The current `test_mplex.py` is a placeholder — it tests
generic RPC echo/iterator plumbing, not the MPlex part itself. There is
no `part.MPlex` configuration in its CFG.

#### Integration test approach:

Build a MicroPython-side config that instantiates `part.MPlex` with
fake pin numbers (MicroPython unix port supports `machine.Pin` with
virtual pin numbers), then drive it remotely from CPython via RPC.

```yaml
# CPython-side config
app: dir
r:
  app: _test.MpyCmd
  cfg:
    app:
      app: dir
      m:
        app: part.MPlex
        scan: [0, 1]       # 2 scan rows
        input: [2, 3]      # 2 input cols → 4 virtual buttons
        output: []         # no outputs for input-only test
        msec: 50           # 50ms scan interval
        timer: 0
      r:
        app: stdio.StdIO
        link: &link
          lossy: false
          guarded: false
          frame: 0x85
  link: *link
```

#### Integration test cases:

1. **`test_mpx_read_initial`** — Remote `cmd_r(0)` returns the initial
   state of button 0 (likely `False` / released).

2. **`test_mpx_write_read_output`** — Remote `cmd_w(0, True)` then
   `cmd_o(0)` returns `True`. `cmd_w(0, False)` then `cmd_o(0)` returns
   `False`.

3. **`test_mpx_stream_changes`** — Subscribe to `stream_i`. Simulate
   a pin change on the MicroPython side (may require a test-only helper
   that flips a fake input). Collect streamed `(btn, pressed)` tuples.

4. **`test_mplex_scanning_runs`** — After setup, the scanner is running
   (`this is not None`). Reading any input doesn't crash even with rapid
   scanning.

**Limitation:** The MicroPython unix port's `machine.Pin` is limited —
pins can be created but there's no straightforward way to inject input
values from outside. True button-press simulation may require either:
- A custom `machine.Pin` subclass registered in the MPy test boot
  script (similar to `_fake.Pin` but at the `machine` level).
- Or modifying the part to accept a callable/list of input callbacks
  instead of raw `Pin` objects (test seam).

The most practical approach: create a tiny MicroPython-side test helper
module (`_test_mplex.py` in `_embed/lib/`) that replaces `machine.Pin`
with a controllable fake before the part loads, similar to how
`_test.py` sets `machine.Pin = FakePin` on the CPython side.

---

### Strategy 3: Hybrid — extract pure logic to a testable support module

**Observation:** `support/mplex.py` already contains the pure scanning
algorithm (`Multiplex` class) separate from the `BaseCmd` wrapper. The
`MPlex` part delegates almost all logic to the same algorithms inline
(duplicated, not delegated).

**Option:** If the logic in `part/mplex.py` were refactored to delegate
to `support/mplex.py`'s `Multiplex` class (instantiating it internally),
then `support/mplex.py` could be tested in near-isolation — it only
needs `machine.Pin`, `machine.Timer`, `disable_irq`/`enable_irq`, which
are easier to stub than the full `BaseCmd` machinery.

However, `support/mplex.py` also imports `from machine import ...`
directly, so it faces the same import barrier. The stubbing approach
from Strategy 1 applies equally to both.

**Recommendation:** Strategy 1 (CPython unit tests with mocks) is the
primary path — it's self-contained, doesn't require the MicroPython
build, and covers the core algorithm. Strategy 2 (integration) is
secondary, valuable for validating the `BaseCmd`/RPC/streaming glue and
the hardware timer interaction, but depends on the `mpy-unix` build
being available and solving the input-injection problem.

## Summary Table

| Layer | Strategy | Dependency | Coverage |
|-------|----------|------------|----------|
| Scanning algorithm, bitmasks, change tracking | 1: CPython + mocks | `sys.modules` stubs | Core logic, all edge cases |
| RPC commands (r/w/o), streaming (stream_i) | 2: MicroPython integration | `mpy-unix` build | End-to-end, real timer/IRQ |
| BaseCmd lifecycle (setup/task/teardown) | 1+2 | both | Init, start/stop, cleanup |

## Recommended Priority

1. **Strategy 1** — implement first, no external dependencies, covers
   the bug-prone bitmask arithmetic and inversion logic.
2. **Strategy 2** — add once the `mpy-unix` build is available; solve
   input injection via a MicroPython-side fake-pin helper.
3. **Refactoring consideration** — consider having `part/mplex.py`
   delegate to `support/mplex.py`'s `Multiplex` class to avoid logic
   duplication and centralize the testable algorithm.
