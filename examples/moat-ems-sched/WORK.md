# Work: Repair `moat.ems.sched` and add a real test

Tracking note: this file documents the work tracked by Beads issue
**moat-emssched-break** (the main bug). A second issue,
**moat-emssched-test**, depends on (is blocked by) it and references
this document.

## Background

`examples/moat-ems-sched/test.py` is a throwaway script that imports
`FutureData`, `Hardware`, and `Model` from `moat.ems.sched`. Commit
`e11e393` ("Massive re-work to support multiple inputs / outputs")
removed `FutureData` (replaced by duck-typed `attrdict` chunks from
async `Loader` plugins) and deleted `Hardware` (folded into the config
tree). The example no longer runs.

More importantly, the *replacement* code in `moat/ems/sched` is itself
broken, so the scheduler doesn't work at all — not just the example.

## Bugs

### Stale `moat.bms.sched` references (typo from a `bms`→`ems` rename)

`load_ext("moat.bms.sched.mode.…")` resolves to `None`, so every
`Loader()` call dies with `AttributeError`. Breaks the library and the
`moat ems sched analyze` CLI outright.

- `moat/ems/sched/mode/__init__.py` — `Loader()`
- `moat/ems/sched/_main.py` — local `Loader()`, `@load_subgroup(prefix=…)`,
  and `list_ext(…)` (three sites)

Fix: `moat.bms.sched` → `moat.ems.sched` everywhere. Also stop
re-defining `Loader` in `_main.py`; import the canonical one from
`mode/__init__.py` to prevent this class of drift recurring.

### `Model.propose()` crashes and returns nothing

- `control.py`: `tg.start_soon(res, cfg, val)` passes `val` (a dict)
  positionally into `result(cfg, **kw)`, which only accepts keyword
  args. Must be `tg.start_soon(res, cfg, **val)`.
- `propose()` returns `None`, contradicting its docstring ("Output
  (first period): grid input … battery SoC …"). Callers — notably the
  hardware driver that acts on the next step — have no way to read the
  decision except by wiring up a file-writing sink. Restore the
  `(grid, soc, money)` return computed from the first-period solution
  vars (`self.g_buy`/`self.g_sell`/`self.cap`/`self.money`), exactly as
  the pre-`e11e393` code did, while still driving the sinks for the
  CLI `--all` full-trajectory case.

### Latent bugs in the `file`-mode sinks (`moat/ems/sched/mode/file.py`)

- `results()`: `StdCBOR.encode` / `StdMsgpack.encode` are referenced as
  bare class attributes; should be `Codec().encode` instances (as the
  `result()` path already does correctly).
- `results()` `json` branch references an undefined `res` (built only
  in the cbor/msgpack branches).

These aren't on the example's hot path but blow up `--all` with
cbor/msgpack/json. Cheap to fix while here.

## Plan

1. Fix the `bms`→`ems` typos; consolidate the duplicated `Loader`.
2. Fix `propose()` sink dispatch (`**val`) and restore its
   `(grid, soc, money)` return.
3. Fix the `file`-mode sink bugs.
4. Convert the example into a real pytest suite under
   `tests/moat_ems_sched/`:
   - Use the real `file` + `file2` modes with `tmp_path` data files
     (doubles as a production-mode regression test).
   - Reproduce the example's `price_buy = (price+0.2)*1.2` via `file2`
     with `factor=1.2`, `offset=0.24`.
   - Obtain config defaults via the `cfg` fixture; override
     `battery`/`inverter`/`grid`/`steps` to match the example's
     `Hardware`.
   - Pass an explicit slot-aligned `t` to satisfy `Model.__init__`.
   - Cases: single `propose(0.3)` sanity; full 24-period trajectory
     (via `results` sink) with SoC-bound and cumulative-money checks;
     bounded 100-step rolling loop mirroring the original demo.
   - `pytest.mark.anyio` (conftest pins trio); redirect output to a
     temp logfile per AGENTS.md.
5. Remove `examples/moat-ems-sched/test.py`; update its `README` /
   `params.yaml` (obsolete `moat bms sched …` invocations and
   `bms/sched/example/…` paths) — repoint to `moat ems sched …` or
   drop.
6. Hygiene: make touched files `ty`-clean; add `"moat/ems/sched/"` to
   `[tool.ty.src].include` in the root `pyproject.toml` (flag any
   pre-existing errors in untouched files as follow-ups, don't expand
   scope).

## Scope guardrails

- Don't refactor unrelated code.
- Don't touch the network modes (`awattar`, `fore_solar`) beyond what's
  needed for the typo fix.
- One commit per logical change; reference the issue in the first
  line.
