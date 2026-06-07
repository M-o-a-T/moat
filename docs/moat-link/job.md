(moat-link-job)=
# Background jobs

The ``moat.link.job`` module provides a background job runner that
behaves like the legacy ``moat kv job`` runner, but stores both job
definitions and dynamic run state in MoaT-Link.

## Storage layout

Two configurable paths control where job data lives:

| Configuration key | Default | Purpose |
|---|---|---|
| ``link.job.prefix`` | ``job`` | Static job records (retained). |
| ``link.job.state`` | ``run.job`` | Dynamic per-run state (retained, despite the ``run.*`` prefix). |

Code snippets executed by jobs are resolved through
:func:`moat.link.client.LinkSender.code_at`, i.e. they live under
:data:`moat.link.code.CODE_EXEC_ROOT` (``code``).

Both top-level paths are extended with a mode tag (``any``, ``at``, or
``all`` from ``link.job.sub``) plus the user-supplied subpath.

## Coordination modes

Three classes mirror the three kv runner modes:

* :class:`~moat.link.job.AnyJobRunner` – exactly one cluster member runs each job.
* :class:`~moat.link.job.SingleJobRunner` – the job runs on one named node.
* :class:`~moat.link.job.AllJobRunner` – the job runs on every node.

## Command-line usage

The CLI mirrors ``moat kv job``:

```
moat link job [-n NODE] [-g GROUP] info
moat link job [-n NODE] [-g GROUP] at PATH list|get|set|delete|state|path
moat link job [-n NODE] [-g GROUP] run [-n NODES]
moat link job [-n NODE] [-g GROUP] monitor
```

``-n``/``--node`` selects the coordination mode (omit for any-one,
``-n NAME`` for a single named node, ``-n -`` for all nodes).

``-g``/``--group`` selects the job group (default: ``default``).
