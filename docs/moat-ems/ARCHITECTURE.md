# Architecture — moat.ems

Home/solar energy management for Victron MultiPlus inverters and DIY battery
packs. Three cooperating concerns: battery monitoring/protection (BMS),
real-time inverter control, and offline charge/discharge cost optimization.

## Battery (`ems/battery/`)

- **`Battery`** (`battery/_base.py`, 778 lines) — core BMS base. Commands
  `cmd_c` (charge state), `cmd_u` (voltage sum), `cmd_t`/`cmd_tb`
  (temperatures), `cmd_lim` (charge/discharge limits). Hierarchy of
  `BatteryAlert` subclasses (`HighSOC`, `LowSOC`, `HighVoltage`,
  `LowCellVoltage`, `CellImbalance`, `HighTemperature`, …) proxied via
  `moat.lib.proxy.as_proxy`.
- **`BattComm`** (`battery/diy_serial/comm.py`) — `BaseCmd` subclass
  implementing the diyBMS serial protocol: encodes control packets, forwards
  them "to the link," decodes replies with sequencing/retry.

## Inverter (`ems/inv/`)

- **`InvControl`**, **`InvInterface`**, **`BusVars`**, **`InvModeBase`**
  (`inv/__init__.py`, 1348 lines) — the inverter controller. `InvControl`
  holds a `MODES` registry and physical/electrical calc helpers
  (`calc_grid_p`, `calc_inv_p`, `i_from_p`, `p_from_i`); `InvInterface` is a
  D-Bus service exposing `GetModes/SetMode/SetModeParam/GetState`.
- **Inverter modes** (subclass `InvModeBase`): `InvMode_Remote` (`remote.py`,
  dynamic grid-feed with DistKV-monitored limits/power), `InvMode_SetSOC`
  (`set_soc.py`), `InvMode_Analyze` (`analyze.py`, multi-step battery
  capacity calibration), plus `grid_power.py`, `idle.py`, `off.py`,
  `inv_power.py`, `batt_current.py`.

## Scheduler (`ems/sched/`)

- **`Model`** (`sched/control.py`) — LP optimizer wrapping Google OR-Tools
  (`pywraplp`, GLOP). Builds variables/constraints for battery SoC, grid
  buy/sell, solar, load per period; maximizes net income; `propose(charge)`
  solves and emits per-period grid power / SoC / earnings.
- **`BaseLoader`** (`sched/mode/__init__.py`) — interface for pluggable
  data-source loaders (`price_buy`, `price_sell`, `solar`, `load`, `soc`,
  `result`, `results`). Implementations: `file.py` (yaml/cbor/msgpack/json),
  `awattar.py` (Awattar spot-price API), `fore_solar.py` (forecast.solar API),
  `file2.py`.

## Victron D-Bus layer (`ems/victron/dbus/`)

`Dbus` (`__init__.py`), `DbusMonitor` (`monitor.py`), helpers
`CtxObj`/`DbusInterface`/`DbusName` (`utils.py`).

## Integration with rest of MoaT

- **Battery** relies on the MoaT micro/RPC stack: `moat.lib.rpc` (`RootCmd`,
  `BaseCmd`, `ArrayCmd`, `SubMsgSender`), `moat.lib.micro` (events, locks,
  timeouts), `moat.micro.rtc`, `moat.micro.cmd.alert.AlertHandler`,
  `moat.micro.part.relay.Relay`. Offline frontend `battery/OFF/_main.py`
  obtains a connection via `moat.micro.main.get_link` and issues RPC
  `req.send(["loc", app, "state"])`; `diy_serial/comm.py` forwards packets to
  a comms sub-object resolved from the RPC tree (`self.root.sub_at(cfg["comm"])`).
- **Inverter** does **not** use moat.link. It talks to Victron Venus OS over
  the system D-Bus (`asyncdbus`), reaches the BMS through D-Bus proxies
  (`org.m_o_a_t.bms`), and coordinates distributed state via **DistKV**
  (`moat.kv.client.open_client`) — reading/writing `solar/limit`,
  `solar/power`, `solar/energy`, etc.
- **Scheduler** is essentially standalone: consumes config + pluggable async
  data loaders, runs OR-Tools, writes results via callbacks/files. No
  link/RPC/D-Bus coupling.

Some CLIs retain legacy `moat.bms.*` subgroup prefixes (`sub_pre="moat.bms"`
in `battery`) despite living under `moat.ems.*` — evidence of a `bms→ems`
rename. The scheduler's CLI was migrated to `moat.ems.sched` and no longer
carries the stale `bms` prefix.

## Entry points

- `ems/_main.py`: `cli` via `load_subgroup(sub_pre="moat.ems")`.
- `battery/_main.py`: `cli` (`moat.bms` subgroup) → `cell state`/`cell cfg`,
  opening a `RootCmd` to the battery.
- `battery/OFF/_main.py`: `cli` → `state` (uses `get_link`).
- `inv/_main.py`: standalone `cli` connecting to system D-Bus, calling
  `InvControl.run(mode)`; runnable directly (`if __name__=="__main__"`).
- `sched/_main.py`: `cli` (`moat.ems.sched`) → `dump`, `modes`, `analyze`
  (runs `Model.propose`).
