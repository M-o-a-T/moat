"""
The ``errors`` unit: the heat pump's error aggregator (HEAT.md §3.7).

It watches the heat pump's error subtree, drops the codes and entries
that are known to be harmless, and publishes the remaining errors with
their overall severity to ``app.heat.errors.out``. It does not stop
anything itself; the pump and selector units act on its output.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict

from moat.lib.path import (
    P,
    Path,  # pydantic needs it at runtime
)
from moat.util.time import time

from .config import UnitCfg
from .link import Reader, TreeReader, is_up, out_path
from .override import reader as override_reader
from .state import State
from .unit import Step, Unit

from collections.abc import Mapping
from typing import Any

__all__ = ["STALE", "ErrorsCfg", "ErrorsCore", "ErrorsState", "ErrorsUnit", "Severity"]

STALE = "stale"
"""The key, and the code, of the synthetic error that reports a stale error feed."""


class Severity(StrEnum):
    """How bad the current errors are, in ascending order."""

    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Position in the order ``none`` < ``warning`` < ``critical``."""
        return _RANK[self]


_RANK = {Severity.NONE: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}


class ErrorsCfg(UnitCfg):
    """Configuration of the errors unit."""

    model_config = ConfigDict(strict=False)  # severities arrive as strings

    feed: Path = P("heat.s.pump.err")
    """The error subtree (``sensor.error``). Each item holds an error code; 0 means no error."""
    override: Path = P("app.heat.override.errors")
    """
    Operator-injected errors (HEAT.md §2.7), as ``{value: {key: code}, …}``.

    The mapping must be wrapped in ``value``, as a bare mapping is
    read as the override's metadata.
    """

    ignore_codes: list[int] = [30055]
    """Codes that are not errors. 30055 is a communication error."""
    ignore_paths: list[Path] = [P(":1")]
    """Entries, relative to `feed`, that are not errors."""
    severity: dict[int, Severity] = {}
    """Severity of specific codes."""
    default_severity: Severity = Severity.CRITICAL
    """Severity of codes not listed in `severity`."""

    source: Path | None = None
    """
    The service announcement of whatever writes the feed.

    While it is not up, the feed is stale. Error codes are published on
    change, so their age says nothing about the feed's health.
    """


class ErrorsState(State):
    """Persistent state of the errors unit."""

    model_config = ConfigDict(strict=False, use_enum_values=True, validate_default=True)

    severity: Severity = Severity.NONE
    """The published severity."""
    since: float | None = None
    """When `severity` last changed (wall-clock time)."""


class ErrorsCore:
    """
    Sans-IO core of the errors unit.

    Inputs: ``feed`` (the error subtree, relative path → code),
    ``override`` (injected errors, key → code) and, if configured,
    ``source`` (the feed writer's service announcement).
    """

    def __init__(self, cfg: ErrorsCfg, state: ErrorsState, now: float) -> None:  # noqa: ARG002
        self.cfg = cfg
        self.state = state

    def update_cfg(self, cfg: ErrorsCfg) -> None:
        """Apply a changed configuration."""
        self.cfg = cfg

    def _severity(self, code: Any) -> Severity:
        if code == STALE:
            return Severity.CRITICAL
        return self.cfg.severity.get(code, self.cfg.default_severity)

    def step(self, inputs: dict[str, Any], now: float) -> Step:  # noqa: ARG002
        """Collect the errors."""
        cfg = self.cfg
        feed: Mapping[Path, Any] = inputs.get("feed") or {}
        errors: dict[str, Any] = {}
        for path, code in feed.items():
            if code and code not in cfg.ignore_codes and path not in cfg.ignore_paths:
                errors[str(path)] = code
        ovr = inputs.get("override")
        if isinstance(ovr, Mapping):
            errors.update((str(k), v) for k, v in ovr.items() if v)
        if cfg.source is not None and not is_up(inputs.get("source")):
            errors[STALE] = STALE

        sev = max(
            (self._severity(c) for c in errors.values()),
            key=lambda s: s.rank,
            default=Severity.NONE,
        )
        save = False
        if sev != self.state.severity or self.state.since is None:
            self.state.severity = sev
            self.state.since = time()
            save = True

        out = {"errors": errors, "severity": str(sev), "since": self.state.since}
        return Step(outputs={out_path("errors"): out}, save_now=save)


class ErrorsUnit(Unit[ErrorsCfg, ErrorsState]):
    """MoaT-Link adapter of the errors unit."""

    name = "errors"
    cfg_model = ErrorsCfg
    state_model = ErrorsState

    def make_core(self, cfg: ErrorsCfg, state: ErrorsState, now: float) -> ErrorsCore:
        """The core."""
        return ErrorsCore(cfg, state, now)

    def make_inputs(self, cfg: ErrorsCfg) -> dict[str, Reader[Any]]:
        """The error subtree, the override, and the feed writer's announcement if configured."""
        res: dict[str, Reader[Any]] = {
            "feed": TreeReader(self.link, cfg.feed),
            "override": override_reader(self.link, "errors", cfg.override),
        }
        if cfg.source is not None:
            res["source"] = Reader[Any](self.link, cfg.source)
        return res
