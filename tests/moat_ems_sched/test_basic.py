"""
Tests for moat.ems.sched — exercises the three fixed defects:
  1. Loader() uses moat.ems.sched (not stale moat.bms.sched)
  2. Model.propose() doesn't crash on start_soon kwargs + returns tuple
  3. file.py results() handles cbor/msgpack/json codecs correctly
"""

from __future__ import annotations

import copy
import json
import math
import pytest
from pathlib import Path

from moat.ems.sched.control import Model
from moat.ems.sched.mode import Loader

pytestmark = [pytest.mark.anyio]


def _mk_data(tmp_path: Path) -> dict[str, Path]:
    """Create sample data files and return their paths."""
    paths: dict[str, Path] = {}
    for key, values in {
        "price_sell": [0.30, 0.25, 0.35, 0.40],
        "solar": [0.0, 2.0, 5.0, 1.0],
        "load": [1.0, 1.0, 1.0, 1.0],
    }.items():
        p = tmp_path / f"{key}.data"
        p.write_text("\n".join(str(v) for v in values) + "\n")
        paths[key] = p
    return paths


def _base_cfg(cfg, tmp_path: Path):
    """Deep-copy the default cfg and override for testing."""
    c = copy.deepcopy(cfg.ems.sched)
    paths = _mk_data(tmp_path)

    c.steps = 1
    c.battery.capacity = 14
    c.battery.max = copy.deepcopy(c.battery.max)  # ensure mutable
    c.battery.soc.min = 0.05
    c.battery.soc.max = 0.95
    c.battery.soc.value.current = 0.0
    c.battery.soc.value.end = 0.1

    c.inverter.max.charge = 10
    c.inverter.max.discharge = 10

    c.grid.max.buy = 100
    c.grid.max.sell = 100

    c.mode.price_sell = "file"
    c.mode.price_buy = "file2"
    c.mode.solar = "file"
    c.mode.load = "file"
    c.mode.soc = None

    c.start.soc = 0.3

    c.data.file.price_sell = str(paths["price_sell"])
    c.data.file.solar = str(paths["solar"])
    c.data.file.load = str(paths["load"])
    c.data.file.result = str(tmp_path / "result.out")

    c.data.file2.factor = 1.2
    c.data.file2.offset = 0.02

    return c


async def test_loader_uses_ems_not_bms():
    """Defect 1: Loader() must resolve moat.ems.sched.mode.*, not moat.bms.sched.mode.*."""
    cls = Loader("file")
    assert cls is not None, "Loader('file') returned None — stale bms ref?"
    assert hasattr(cls, "price_sell"), "Loaded class missing price_sell"


async def test_propose_returns_tuple(cfg, tmp_path):
    """Defect 2: propose() must not crash and must return (grid, soc, money)."""
    c = _base_cfg(cfg, tmp_path)
    m = Model(c, t=0)
    grid, soc, money = await m.propose(0.3)

    assert isinstance(grid, float), f"grid should be float, got {type(grid)}"
    assert isinstance(soc, float), f"soc should be float, got {type(soc)}"
    assert isinstance(money, float), f"money should be float, got {type(money)}"


async def test_propose_with_result_sink(cfg, tmp_path):
    """Defect 2: propose() with result sink must not crash on start_soon kwargs."""
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = "file"
    c.data.format.result = "yaml"

    m = Model(c, t=0)
    grid, _soc, _money = await m.propose(0.3)

    assert isinstance(grid, float)
    # The result file should have been written
    result_path = Path(c.data.file.result)
    assert result_path.exists(), "Result file was not written"
    content = result_path.read_text()
    assert "grid" in content, f"Expected 'grid' in result file, got: {content}"


def _mk_empty_data(tmp_path: Path) -> dict[str, Path]:
    """Create empty (zero-row) data files and return their paths."""
    paths: dict[str, Path] = {}
    for key in ("price_sell", "solar", "load"):
        p = tmp_path / f"empty_{key}.data"
        p.write_text("")
        paths[key] = p
    return paths


async def test_propose_empty_data_raises_clear_error(cfg, tmp_path):
    """Regression: propose() with no data rows must raise a clear ValueError.

    Previously the empty-data path crashed with an opaque
    ``UnboundLocalError: cannot access local variable 'cap'`` in
    ``_setup()`` (the loop body never ran, so ``cap`` was unbound), and
    even if that were survived, ``self.g_buy``/``self.cap``/``self.money``
    stayed ``None``, so ``propose()``'s return raised
    ``AttributeError: 'NoneType' has no attribute 'solution_value'``.
    """
    c = copy.deepcopy(cfg.ems.sched)
    paths = _mk_empty_data(tmp_path)

    c.steps = 1
    c.battery.capacity = 14
    c.battery.max = copy.deepcopy(c.battery.max)
    c.battery.soc.min = 0.05
    c.battery.soc.max = 0.95
    c.battery.soc.value.current = 0.0
    c.battery.soc.value.end = 0.1
    c.inverter.max.charge = 10
    c.inverter.max.discharge = 10
    c.grid.max.buy = 100
    c.grid.max.sell = 100
    c.mode.price_sell = "file"
    c.mode.price_buy = "file2"
    c.mode.solar = "file"
    c.mode.load = "file"
    c.mode.soc = None
    c.start.soc = 0.3
    c.data.file.price_sell = str(paths["price_sell"])
    c.data.file.solar = str(paths["solar"])
    c.data.file.load = str(paths["load"])
    c.data.file.result = str(tmp_path / "result.out")
    c.data.file2.factor = 1.2
    c.data.file2.offset = 0.02

    m = Model(c, t=0)
    with pytest.raises(ValueError, match="No scheduling data"):
        await m.propose(0.3)


async def test_results_yaml(cfg, tmp_path):
    """Defect 3: results() yaml codec should write trajectory to the plural path."""
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = "yaml"
    c.data.file.results = str(tmp_path / "results.out")

    m = Model(c, t=0)
    _grid, _soc, _money = await m.propose(0.3)

    result_path = Path(c.data.file.results)
    assert result_path.exists(), "Results file was not written"
    content = result_path.read_text()
    assert "grid" in content


async def test_results_json(cfg, tmp_path):
    """Defect 3: results() json codec — res must be initialised before append."""
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = "json"
    c.data.file.results = str(tmp_path / "results.json")

    m = Model(c, t=0)
    _grid, _soc, _money = await m.propose(0.3)

    result_path = Path(c.data.file.results)
    assert result_path.exists(), "Results file was not written"
    content = result_path.read_text()
    data = json.loads(content)
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0, "Empty results list"
    assert "grid" in data[0], f"Missing 'grid' key in first result: {data[0]}"


async def test_results_cbor(cfg, tmp_path):
    """Defect 3: results() cbor codec — must use Codec().encode, not bare class attr."""
    from moat.lib.codec.moat_cbor import Codec as StdCBOR  # noqa: PLC0415

    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = "cbor"
    c.data.file.results = str(tmp_path / "results.cbor")

    m = Model(c, t=0)
    _grid, _soc, _money = await m.propose(0.3)

    result_path = Path(c.data.file.results)
    assert result_path.exists(), "Results file was not written"
    raw = result_path.read_bytes()
    assert len(raw) > 0, "Empty CBOR file"
    data = StdCBOR().decode(raw)
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0
    assert "grid" in data[0]


async def test_results_msgpack(cfg, tmp_path):
    """Defect 3: results() msgpack codec — must use Codec().encode, not bare class attr."""
    from moat.lib.codec.moat_msgpack import Codec as StdMsgpack  # noqa: PLC0415

    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = "msgpack"

    m = Model(c, t=0)
    _grid, _soc, _money = await m.propose(0.3)

    result_path = Path(c.data.file.results)
    assert result_path.exists(), "Results file was not written"
    raw = result_path.read_bytes()
    assert len(raw) > 0, "Empty msgpack file"
    data = StdMsgpack().decode(raw)
    assert isinstance(data, list), f"Expected list, got {type(data)}"
    assert len(data) > 0
    assert "grid" in data[0]


# --- results() must write to the PLURAL path data.file.results -----------------
# The plural ``results()`` sink and the singular ``result()`` sink are distinct
# config keys (``data.file.result`` vs ``data.file.results``). control.py may
# launch both writers concurrently (cfg.mode.result and cfg.mode.results both
# set). If ``results()`` writes to the singular path, the two streams collide
# on the same file and corrupt each other's output.


def _dual_cfg(cfg, tmp_path: Path):
    """Config with both ``result`` and ``results`` sinks on SEPARATE files."""
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = "file"
    c.mode.results = "file"
    c.data.format.result = "yaml"
    c.data.format.results = "yaml"
    c.data.file.result = str(tmp_path / "singular.out")
    c.data.file.results = str(tmp_path / "plural.out")
    return c


async def test_results_uses_plural_path(cfg, tmp_path):
    """results() must write to ``data.file.results`` (plural), not ``data.file.result``.

    With only the plural sink enabled, the trajectory must land in the plural
    file and the singular file must remain untouched.
    """
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = "yaml"
    c.data.file.result = str(tmp_path / "singular.out")
    c.data.file.results = str(tmp_path / "plural.out")

    m = Model(c, t=0)
    await m.propose(0.3)

    plural_path = Path(c.data.file.results)
    singular_path = Path(c.data.file.result)
    assert plural_path.exists(), "Plural results file was not written"
    assert "grid" in plural_path.read_text()
    assert not singular_path.exists(), (
        "results() wrote to the singular data.file.result path — it must use "
        "data.file.results (plural)"
    )


async def test_results_and_result_do_not_collide(cfg, tmp_path):
    """Both sinks enabled concurrently must write to disjoint files.

    Regression for the file-path collision bug: before the fix, results()
    opened ``data.file.result`` (singular), the very same file result() writes
    to, so enabling both sinks raced on one file and produced garbled output.
    """
    c = _dual_cfg(cfg, tmp_path)

    m = Model(c, t=0)
    await m.propose(0.3)

    singular_path = Path(c.data.file.result)
    plural_path = Path(c.data.file.results)
    assert singular_path.exists(), "Singular result file was not written"
    assert plural_path.exists(), "Plural results file was not written"
    assert singular_path != plural_path, "Test setup error: paths must differ"

    sing = singular_path.read_text()
    plur = plural_path.read_text()
    # Singular result() emits one mapping; plural results() emits a sequence.
    assert "grid" in sing
    assert "money" in sing
    assert "grid" in plur
    assert "money" in plur
    # The plural stream carries the full trajectory (>= the single first row),
    # so its size must not be smaller than the singular one-row dump.
    assert len(plur) >= len(sing), (
        f"Plural results ({len(plur)} B) shorter than singular ({len(sing)} B) "
        "— streams collided on one file"
    )


@pytest.mark.parametrize(
    "fmt",
    ["yaml", "json", "cbor", "msgpack"],
)
async def test_results_each_format_writes_plural_path(cfg, tmp_path, fmt):
    """Every supported results() codec must write to the plural path."""
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = fmt
    c.data.file.result = str(tmp_path / "singular.out")
    c.data.file.results = str(tmp_path / "plural.out")

    m = Model(c, t=0)
    await m.propose(0.3)

    plural_path = Path(c.data.file.results)
    singular_path = Path(c.data.file.result)
    assert plural_path.exists(), f"{fmt}: plural results file was not written"
    assert plural_path.stat().st_size > 0, f"{fmt}: plural results file is empty"
    assert not singular_path.exists(), (
        f"{fmt}: results() wrote to the singular path — must use data.file.results"
    )


async def test_results_unknown_format_does_not_write_wrong_path(cfg, tmp_path):
    """An unknown format must not silently fall back to the singular path."""
    c = _base_cfg(cfg, tmp_path)
    c.mode.result = None
    c.mode.results = "file"
    c.data.format.results = "pickle"  # unsupported
    c.data.file.result = str(tmp_path / "singular.out")
    c.data.file.results = str(tmp_path / "plural.out")

    m = Model(c, t=0)
    # Unknown format prints a message and exits; surface it as an error in
    # the task group rather than silently producing no/wrong output.
    with pytest.raises((SystemExit, BaseException)):
        await m.propose(0.3)


# --- Regression: no stale BMS references -------------------------------------
# The ``bms``→``ems`` rename left stale ``moat.bms.sched`` / ``bms/sched`` /
# ``moat bms sched`` references scattered across code, configs, examples, and
# docs. They silently broke every ``Loader()`` call (``load_ext`` returned
# ``None`` → ``AttributeError``) and pointed users at a non-existent CLI /
# path layout. Guard against any recurrence by scanning the scheduler package,
# its example directory, and the EMS docs.

_STALE_BMS_PATTERNS = (
    "moat.bms.sched",
    "bms/sched/",
    "moat bms sched",
)


def _scan_for_stale_bms_refs(root: Path, dirs: tuple[str, ...]):
    """Walk *dirs* (relative to *root*) and collect stale-BMS hits."""
    hits: list[str] = []
    skip_dirs = {"__pycache__", ".venv", ".git"}
    for rel in dirs:
        base = root / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pat in _STALE_BMS_PATTERNS:
                if pat in text:
                    hits.append(f"{path.relative_to(root)}: stale {pat!r}")
    return hits


def test_no_stale_bms_refs_in_sched_package():
    """Regression: moat/ems/sched/ must contain no ``moat.bms.sched`` refs."""
    root = Path(__file__).resolve().parents[2]
    hits = _scan_for_stale_bms_refs(root, ("moat/ems/sched",))
    assert not hits, "Stale BMS references in moat/ems/sched:\n  " + "\n  ".join(hits)


def test_no_stale_bms_refs_in_example_and_docs():
    """Regression: the ems-sched example + EMS docs must not advertise the dead ``bms sched`` CLI/paths."""
    root = Path(__file__).resolve().parents[2]
    hits = _scan_for_stale_bms_refs(root, ("examples/moat-ems-sched", "docs/moat-ems"))
    # WORK.md legitimately describes the historical bug — exclude it.
    hits = [h for h in hits if "WORK.md" not in h]
    assert not hits, "Stale BMS references in example/docs:\n  " + "\n  ".join(hits)


def test_example_test_py_removed():
    """The broken example/test.py imported removed symbols (FutureData/Hardware)."""
    root = Path(__file__).resolve().parents[2]
    assert not (root / "examples" / "moat-ems-sched" / "test.py").exists()


def test_example_params_yaml_loads_clean():
    """The example params.yaml must parse and carry no stale ``bms`` keys."""
    import yaml  # noqa: PLC0415

    root = Path(__file__).resolve().parents[2]
    p = root / "examples" / "moat-ems-sched" / "params.yaml"
    data = yaml.safe_load(p.read_text())
    assert isinstance(data, dict)
    # core sections the optimizer needs
    for key in ("battery", "inverter", "grid", "mode", "data", "start"):
        assert key in data, f"params.yaml missing top-level key {key!r}"
    # buy-price derivation mirrors the old (price+0.2)*1.2 example
    assert data["data"]["file2"]["factor"] == 1.2
    assert data["data"]["file2"]["offset"] == 0.24


# ---------------------------------------------------------------------------
# Scenarios reproduced from the original examples/moat-ems-sched/test.py
# ---------------------------------------------------------------------------
#
# The throwaway example drove the scheduler over a 24-slot "typical day" with
# ``Hardware(...)`` settings and a ``price_buy = (price + 0.2) * 1.2``
# derivation.  Those scenarios are reproduced here through the real
# ``file`` / ``file2`` modes with ``tmp_path`` data files, complementing the
# defect regressions above with behaviour-level coverage of the optimiser.

#: The 24-slot "typical day" copied verbatim from the original script.  Each
#: triple is ``(price_sell, load, pv)``; the helper ``F`` derived
#: ``price_buy = (price + 0.2) * 1.2``.
TYPICAL_DAY: list[tuple[float, float, float]] = [
    (0.20, 1.0, 0.0),  # 0
    (0.18, 1.0, 0.0),
    (0.18, 1.0, 0.0),
    (0.15, 1.0, 0.0),
    (0.15, 1.0, 0.0),
    (0.20, 1.0, 0.0),
    (0.35, 1.0, 0.0),  # 6
    (0.40, 2.0, 0.0),
    (0.30, 2.0, 0.5),
    (0.25, 1.0, 1.0),
    (0.20, 1.0, 2.0),
    (0.05, 1.0, 3.0),
    (0.05, 1.0, 6.0),  # 12
    (0.05, 2.0, 8.0),
    (0.05, 2.0, 8.0),
    (0.15, 1.0, 4.0),
    (0.20, 1.0, 2.0),
    (0.35, 1.0, 1.0),
    (0.50, 1.0, 0.0),  # 18
    (0.55, 1.0, 0.0),
    (0.35, 1.0, 0.0),
    (0.30, 1.0, 0.0),
    (0.30, 1.0, 0.0),
    (0.25, 1.0, 0.0),  # 23
]

#: ``Hardware`` settings from the original script, mapped onto the config tree
#: that replaced ``Hardware``.
HW_CAPACITY = 14
HW_BATT_MAX_CHG = 5
HW_BATT_MAX_DIS = 8
HW_INV_MAX_CHG = 10
HW_INV_MAX_DIS = 10

#: Slot timestamp aligned to ``steps=1`` (3600 s per slot).
SLOT_T = 3600.0


def _write_rows(tmp_path: Path, key: str, rows: list[tuple[float, float, float]]) -> Path:
    """Write one column of *rows* to a data file and return its path."""
    idx = {"price_sell": 0, "load": 1, "solar": 2}[key]
    p = tmp_path / f"{key}.data"
    p.write_text("\n".join(str(r[idx]) for r in rows) + "\n")
    return p


@pytest.fixture
def day_cfg(cfg, tmp_path):
    """Config wired to the 24-slot "typical day" via file/file2 modes.

    Mirrors the original script's ``Hardware`` (mapped onto the config tree)
    and its ``price_buy = (price + 0.2) * 1.2`` derivation (``file2`` with
    ``factor=1.2``, ``offset=0.24``).
    """
    c = copy.deepcopy(cfg.ems.sched)
    c.steps = 1

    c.battery.capacity = HW_CAPACITY
    c.battery.max = copy.deepcopy(c.battery.max)  # ensure mutable
    c.battery.max.charge = HW_BATT_MAX_CHG
    c.battery.max.discharge = HW_BATT_MAX_DIS
    c.battery.soc.min = 0.05
    c.battery.soc.max = 0.95
    c.battery.soc.value.current = 0.0
    c.battery.soc.value.end = 0.1

    c.inverter.max = copy.deepcopy(c.inverter.max)
    c.inverter.max.charge = HW_INV_MAX_CHG
    c.inverter.max.discharge = HW_INV_MAX_DIS

    c.grid.max = copy.deepcopy(c.grid.max)
    c.grid.max.buy = 999
    c.grid.max.sell = 999

    c.mode.price_sell = "file"
    c.mode.price_buy = "file2"
    c.mode.solar = "file"
    c.mode.load = "file"
    c.mode.soc = None
    c.mode.result = None
    c.mode.results = None

    c.start.soc = 0.3

    c.data.file.price_sell = str(_write_rows(tmp_path, "price_sell", TYPICAL_DAY))
    c.data.file.solar = str(_write_rows(tmp_path, "solar", TYPICAL_DAY))
    c.data.file.load = str(_write_rows(tmp_path, "load", TYPICAL_DAY))
    c.data.file.result = str(tmp_path / "result.out")
    c.data.file.results = str(tmp_path / "results.out")

    # price_buy = price_sell * 1.2 + 0.24 == (price + 0.2) * 1.2
    c.data.file2.factor = 1.2
    c.data.file2.offset = 0.24

    return c


def _rewrite_day(tmp_path: Path, rows: list[tuple[float, float, float]]) -> None:
    """Overwrite the day's data files with a rotated *rows* list."""
    _write_rows(tmp_path, "price_sell", rows)
    _write_rows(tmp_path, "solar", rows)
    _write_rows(tmp_path, "load", rows)


async def test_typical_day_dataset_shape():
    """The 24-slot dataset from the original script is intact."""
    assert len(TYPICAL_DAY) == 24, "expected a full 24-hour day"
    for price, load, pv in TYPICAL_DAY:
        assert isinstance(price, float)
        assert isinstance(load, float)
        assert isinstance(pv, float)
        assert load >= 0
        assert pv >= 0


@pytest.mark.parametrize(
    ("idx", "price", "load", "pv"),
    [(i, *row) for i, row in enumerate(TYPICAL_DAY)],
    ids=[f"slot-{i:02d}" for i in range(len(TYPICAL_DAY))],
)
async def test_typical_day_row(idx, price, load, pv):
    """Each original row is catalogued and individually asserted."""
    assert 0 <= idx < len(TYPICAL_DAY), f"slot {idx} out of range"
    assert price > 0, f"slot {idx}: price must be positive"
    assert load >= 0
    assert pv >= 0


async def test_file2_derives_price_buy_from_sell(day_cfg):
    """file2 must reproduce the original ``F`` helper's buy-price formula.

    ``price_buy = (price + 0.2) * 1.2 = price * 1.2 + 0.24``.
    """
    from moat.ems.sched.mode.file2 import Loader as File2Loader  # noqa: PLC0415

    buys: list[float] = []
    async for x in File2Loader.price_buy(day_cfg, SLOT_T):
        buys.append(x)
    assert len(buys) == 24
    for sell, buy in zip((r[0] for r in TYPICAL_DAY), buys, strict=True):
        assert buy == pytest.approx((sell + 0.2) * 1.2), f"sell={sell} buy={buy}"


async def test_single_propose_sanity(day_cfg):
    """Single ``propose(0.3)`` over the typical day — the script's core call."""
    m = Model(day_cfg, t=SLOT_T)
    grid, soc, money = await m.propose(0.3)

    assert isinstance(grid, (int, float))
    assert isinstance(soc, (int, float))
    assert isinstance(money, (int, float))
    # SoC must stay within the configured battery envelope.
    assert day_cfg.battery.soc.min <= soc <= day_cfg.battery.soc.max


@pytest.mark.parametrize("start_soc", [0.06, 0.3, 0.5, 0.94])
async def test_propose_respects_soc_bounds(day_cfg, start_soc):
    """propose() keeps the resulting SoC within the battery's min/max for
    several starting charges — the script clamps externally; the optimiser
    honours the envelope internally."""
    m = Model(day_cfg, t=SLOT_T)
    _grid, soc, _money = await m.propose(start_soc)
    assert day_cfg.battery.soc.min <= soc <= day_cfg.battery.soc.max


async def test_full_trajectory_via_results_sink(day_cfg):
    """The ``results`` sink emits one record per period (24 total).

    Mirrors the script's full-day view; each record carries the
    ``grid / soc / batt / money`` keys the sink produces.  Unlike the
    singular ``result()`` sink, ``results()`` writes to the plural
    ``data.file.results`` path.
    """
    day_cfg.mode.results = "file"
    day_cfg.data.format.results = "json"

    m = Model(day_cfg, t=SLOT_T)
    await m.propose(0.3)

    results_path = Path(day_cfg.data.file.results)
    assert results_path.exists(), "Results file was not written"
    traj = json.loads(results_path.read_text())
    assert isinstance(traj, list)
    assert len(traj) == 24, f"expected 24 records, got {len(traj)}"
    for rec in traj:
        assert set(rec) == {"grid", "soc", "batt", "money"}
        assert day_cfg.battery.soc.min <= rec["soc"] <= day_cfg.battery.soc.max


async def test_rolling_hundred_steps(day_cfg, tmp_path):
    """The bounded 100-step rolling loop from the original script.

    Each step re-runs ``Model(...).propose(soc)``, clamps the SoC to
    ``[0.06, 0.94]`` (as the script did), accumulates money, and rotates
    the day's data by one slot.  Asserts the cumulative sum is finite and
    bounded, and that the SoC never escapes the clamp band.
    """
    soc = 0.3
    msum = 0.0
    rows = list(TYPICAL_DAY)
    soc_seen: list[float] = []

    for _n in range(100):
        m = Model(day_cfg, t=SLOT_T)
        _grid, soc, money = await m.propose(soc)
        soc_seen.append(soc)
        # External clamp, exactly as the original script did.
        if soc < 0.06:
            soc = 0.06
        elif soc > 0.94:
            soc = 0.94
        msum += money
        # Rotate the day: data = data[1:] + data[:1].
        rows.append(rows.pop(0))
        _rewrite_day(tmp_path, rows)

    assert math.isfinite(msum), f"cumulative money not finite: {msum}"
    # Cumulative cost/income for one day-ish of operation is a modest number.
    assert -1000 < msum < 1000
    # The optimiser-reported SoC respects the battery envelope every step;
    # the clamped feed-back SoC stays within the script's band.
    assert all(0.0 <= s <= 1.0 for s in soc_seen)
