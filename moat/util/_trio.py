# Trio step monitors

from __future__ import annotations
from trio.abc import Instrument
from trio import Cancelled
from trio._core._instrumentation import Instruments
import sys
from outcome import Value, Error


class Instr(Instrument):
    exited = None

    def before_task_step(self, task):
        print("BEF:", task, task._next_send, file=sys.stderr)

    def after_task_step(self, task):
        print("AFT:", task, task._next_send, file=sys.stderr)

    def task_exited(self, task, outcome=None):
        print("EXIT", task, outcome, file=sys.stderr)


def hookup(runner=None):
    if runner is None:
        import inspect as i

        f = i.currentframe().f_back
        while "runner" not in f.f_locals:
            f = f.f_back
            if f is None:
                return  # no Trie
        runner = f.f_locals["runner"]

    i = Instr()
    ig = Instruments([i])
    runner.instruments = ig
