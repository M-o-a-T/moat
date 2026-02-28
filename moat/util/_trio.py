# Trio step monitors

from __future__ import annotations

import sys
from importlib import import_module

from trio.abc import Instrument

from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from types import FrameType

    from outcome import Outcome

    class Runner(Protocol):
        instruments: Any

    class Task(Protocol):
        _next_send: Any


def _instruments(seq: list[Instrument]) -> Any:
    return import_module("trio._core._instrumentation").Instruments(seq)


class Instr(Instrument):
    exited: None = None

    def before_task_step(self, task: Task) -> None:
        print("BEF:", task, task._next_send, file=sys.stderr)  # noqa: SLF001

    def after_task_step(self, task: Task) -> None:
        print("AFT:", task, task._next_send, file=sys.stderr)  # noqa: SLF001

    def task_exited(self, task: Task, outcome: Outcome[Any] | None = None) -> None:
        print("EXIT", task, outcome, file=sys.stderr)


def hookup(runner: Runner | None = None) -> None:
    if runner is None:
        import inspect  # noqa: PLC0415

        f: FrameType | None = inspect.currentframe().f_back  # type: ignore[union-attr]  # currentframe can return None but we know we're in a function
        while f is not None and "runner" not in f.f_locals:
            f = f.f_back
            if f is None:
                return  # no Trio
        if f is None:
            return
        runner = cast(Runner, f.f_locals["runner"])  # f is not None here

    i = Instr()
    ig = _instruments([i])
    runner.instruments = ig
