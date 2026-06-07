"""
Background job execution for MoaT-Link.

This module provides the same kind of background job runner as
``moat kv job``, but stores job definitions and dynamic run state in
the MoaT-Link tree instead of in MoaT-KV.

Static job data lives below :data:`JOB_ROOT_DEFAULT` (``job``), the
dynamic per-run status below :data:`STATE_ROOT_DEFAULT` (``run.job``).
Both paths can be overridden via the ``link.job.prefix`` and
``link.job.state`` configuration keys.

Snippets referenced from a job entry are resolved through
:func:`moat.link.client.LinkSender.code_at`, i.e. they live below
:data:`moat.link.code.CODE_EXEC_ROOT`.
"""

from __future__ import annotations

from moat.lib.path import P

from .runner import (
    AllJobRunner,
    AnyJobRunner,
    CallAdmin,
    ChangeMsg,
    ErrorRecorded,
    JobEntry,
    JobRunner,
    MQTTmsg,
    ReadyMsg,
    RunnerMsg,
    SingleJobRunner,
    StateEntry,
    TimerMsg,
)

#: Default path holding the static job data.
JOB_ROOT_DEFAULT = P("job")

#: Default path holding dynamic run status.
STATE_ROOT_DEFAULT = P("run.job")


__all__ = [
    "JOB_ROOT_DEFAULT",
    "STATE_ROOT_DEFAULT",
    "AllJobRunner",
    "AnyJobRunner",
    "CallAdmin",
    "ChangeMsg",
    "ErrorRecorded",
    "JobEntry",
    "JobRunner",
    "MQTTmsg",
    "ReadyMsg",
    "RunnerMsg",
    "SingleJobRunner",
    "StateEntry",
    "TimerMsg",
]
