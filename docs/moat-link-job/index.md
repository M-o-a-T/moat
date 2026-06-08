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
moat link job [-n NODE] [-g GROUP] at PATH list|get|set|delete|state|path|debug
moat link job [-n NODE] [-g GROUP] run [-n NODES]
moat link job [-n NODE] [-g GROUP] monitor
```

``-n``/``--node`` selects the coordination mode:

* (omitted) – one cluster member runs the job (Any-runner).
* ``-n NAME`` – the job runs on the named node (Single-runner).
* ``-n -`` – the job runs on every node (All-runner).

``-g``/``--group`` selects the job group (default: ``default``).

### ``at PATH debug``

Runs the job in the current process without any actor coordination or
rescheduling.  Useful for poking at a snippet from the command line.

* ``state.node`` is set to the link's connection ID for the duration
  of the call.
* Refuses to start if a different runner already owns the job;
  override with ``-f``/``--force``.
* ``-b``/``--break`` drops into :py:mod:`pdb` immediately before the
  snippet is invoked.
* The usual ``-v``/``-e``/``-p`` attribute options merge into the
  job's stored ``data`` for this run only; the stored record is not
  modified.
* All output emitted via the snippet's ``_log`` logger (at DEBUG and
  up) is mirrored to stderr regardless of the global verbosity.

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
