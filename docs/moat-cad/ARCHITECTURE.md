# Architecture — moat.cad

Tooling and helper libraries for parametric 3D modeling with **build123d** and
**CadQuery** (OpenCASCADE-backed). Geometry shortcuts, mechanical-part
generators, thread profiles, vector math patches, plus CLI to launch the
CQ-Editor and emit G-code. (Genuinely CAD — *not* "computer-aided dispatch".)

## Key modules

- **`lib.py`** (382 lines) — build123d shortcut library: `Cyl`, `Loc`, `LocR`,
  `Up`, `ArcAt`, `PolyCap`, `stack` (loft sequencer), `quarter` (mirror
  symmetry), degree-trig (`sin`/`cos`/`tan`/`atan`), rotation constants
  `R0–R3`/`RX1..`/`RY..`/`RZ..`, `gear_turn` (gear-mesh angle math),
  `read_step`/`read_stl`/`show` (STEP/STL IO + editor display).
- **`thread.py`** — `AngledThread` (generic angled thread builder) and
  `ISO228_Thread`/`ISO1222_Thread` (`bd_warehouse.thread.TrapezoidalThread`
  subclasses with pipe/tripod thread spec tables).
- **`gridbox.py`** — `gridbox(…)`, a CadQuery reimplementation of Zack
  Freedman's Gridfinity storage boxes.
- **`misc.py`** — `Ridge`, `Slider`, `Mount`, `WoodScrew` part builders.
- **`math.py`** — NumPy `rotate(v,k,theta)` + monkey-patches onto
  `cq.Workplane`/`cq.Plane`/`Shape` (`translated`, `rotated`, `at`,
  `rot_x/y/z`, `off_x/y/z`).
- **`export.py`** — monkey-patches `cq.Workplane.export` for fused STEP
  assembly export.
- **`things.py`** — aliases `Box`/`Cone`/`Cylinder`/`Loft`/`Sphere`/`Torus`/
  `Wedge` to CadQuery solid makers.

## Integration with rest of MoaT

Very shallow. Only MoaT touchpoints: `moat.util.InexactFloat` (used by
`lib.D`), `moat.lib.config.register` (in `__init__.py` to register the
`_cfg.yaml` block), and `moat.lib.run.load_subgroup` (CLI plumbing). No link,
RPC, micro, or kv involvement — a self-contained CAD toolkit.

## Entry points

`cad/_main.py`: `cli` (`load_subgroup(sub_pre="moat.cad", …)`) → subcommands:
- **`edit`** — launches CQ-Editor (`python3 -m cq_editor`) with a constructed
  `PYTHONPATH` (from `cfg.cad.base`/`paths`/`env` in `_cfg.yaml`).
- **`run`** — runs an arbitrary CAD script with the same environment.
- **`gcode`** — renders a Jinja2 template from `_templates/<printer>.gcode.jinja`
  (default printer `xl`).
