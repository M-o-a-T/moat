(moat-link-job)=
# The Link: Job Runner

```{include} ../../packaging/moat-link-job/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

The ``moat link job`` command line is structured exactly like
``moat kv job``:

```
moat link job [-n NODE] [-g GROUP] info
moat link job [-n NODE] [-g GROUP] at PATH list|get|set|delete|state|path
moat link job [-n NODE] [-g GROUP] run [-n NODES]
moat link job [-n NODE] [-g GROUP] monitor
```

``-n``/``--node`` selects the coordination mode:

* (omitted) – one cluster member runs the job (Any-runner).
* ``-n NAME`` – the job runs on the named node (Single-runner).
* ``-n -`` – the job runs on every node (All-runner).

``-g``/``--group`` selects the job group (default: ``default``).

## Storage layout

Two configurable paths control where job data lives:

| Configuration key | Default | Purpose |
|---|---|---|
| ``link.job.prefix`` | ``job`` | Static job records (retained). |
| ``link.job.state`` | ``run.job`` | Dynamic per-run state. |

Code snippets executed by jobs are resolved through
:func:`moat.link.client.LinkSender.code_at`, i.e. they live under
:data:`moat.link.code.CODE_EXEC_ROOT` (``code``).

Both top-level paths are extended with a mode tag (``any``, ``at``, or
``all`` from ``link.job.sub``) plus the user-supplied subpath.

```{toctree}
:maxdepth: 2
:hidden:

api
```
