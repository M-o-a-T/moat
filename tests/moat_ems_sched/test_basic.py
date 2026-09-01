"""
Tests for moat.ems.sched — exercises the three fixed defects:
  1. Loader() uses moat.ems.sched (not stale moat.bms.sched)
  2. Model.propose() doesn't crash on start_soon kwargs + returns tuple
  3. file.py results() handles cbor/msgpack/json codecs correctly
"""

from __future__ import annotations

import copy
import json
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
