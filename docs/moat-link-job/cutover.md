(moat-link-job-cutover)=
# Moving from ``moat kv job`` to ``moat link job``

This is the procedure for switching a MoaT installation's background jobs
from the MoaT-KV runner to the MoaT-Link runner. It is rehearsed against a
test server by ``tests/moat_link_job/test_cutover.py``.

Steps 1 to 3 are read-only or write to trees that nothing uses yet;
steps 4 and 5 switch the runners. Never let a KV runner
and a Link runner work on the same group at the same time: both would
write the same destinations, and timers (``timer.auto_off``) would fire
twice.

## 0. Prerequisites

* Every host that runs KV job runners has ``moat-link-job`` (with the
  ``moat-link-job-*`` units and ``/usr/lib/moat/link/job/run-*``) and a
  working MoaT-Link client configuration. Installing the package starts
  ``moat-link-job.service`` (the ``default`` any-node runner); that is
  harmless as long as ``job.any.default`` is empty.
* A working directory for the backups:

  ```sh
  mkdir -p ~/cutover && cd ~/cutover
  ```

## 1. Inventory (read-only)

On every host, note which KV runners run:

```sh
systemctl list-units --all 'moat-kv-run-*'
```

Each ``moat-kv-run-any[@GROUP]``, ``moat-kv-run-all[@GROUP]`` and
``moat-kv-run-single[@GROUP]`` unit gets a Link counterpart in step 5.
For single-node runners, also note the host's ``NAME`` from
``/etc/moat/kv.env``: the converter keeps KV node names, so the Link
runner must use the same one.

Dump the KV job records, and save the current Link state:

```sh
moat kv data :.moat.kv.run get -r > kv-jobs.yaml
moat link data job get -r > link-jobs-before.yaml      # probably empty
for f in /src/moat/examples/moat-link-job/*.yaml ; do
    s=$(basename $f .yaml)
    moat link code $s get -r > code-$s.yaml 2>/dev/null || echo "$s: new"
done
```

## 2. Dry run (read-only)

```sh
moat link job migrate-from-kv -i kv-jobs.yaml > report-1.yaml
```

Check the report:

* ``groups``: the jobs per mode and group. Every entry needs a runner in
  step 5 (``any.dev`` → ``moat-link-job@dev``, ``all.default`` →
  ``moat-link-job-all``, ``at.NODE.GROUP`` → ``moat-link-job-single@GROUP``
  on NODE, …).
* ``missing_code``: snippets that step 3 must provide. Anything left over
  after step 3 has not been ported; don't proceed.
* ``missing_data``: data paths that don't exist in MoaT-Link. Some are
  written by the job itself (a destination that has never been set); the
  rest point at MoaT-KV-only trees and need a decision per job.
* ``kv_internal``: paths below ``:.moat.kv``. These jobs can't work
  unchanged.
* ``notes``: per job, KV fields that were dropped or changed.
* ``skipped``: KV entries that aren't jobs (groups without code).

## 3. Load the ported snippets (writes ``code.*``)

```sh
moat link code : import /src/moat/examples/moat-link-job/*.yaml
moat link code : test-all
```

``import`` replaces the snippets and their test cases. ``test-all`` must
pass. Then repeat step 2 (``report-2.yaml``); ``missing_code`` must be
empty.

Rollback: ``moat link code : import code-*.yaml`` restores the saved
versions; delete the snippets that were new (``moat link code PATH
delete``).

## 4. Stop the KV runners (outage starts)

On every host, stop and disable the units noted in step 1:

```sh
systemctl disable --now moat-kv-run-any moat-kv-run-any@dev …
```

Nothing runs jobs from here until step 5. Dump the records again: the
KV runner may have updated them since step 1.

```sh
moat kv data :.moat.kv.run get -r > kv-jobs.yaml
```

Rollback: ``systemctl enable --now`` the same units.

## 5. Write the Link jobs and start the runners (writes ``job.*``)

```sh
moat link job migrate-from-kv -i kv-jobs.yaml -w > report-write.yaml
```

The report lists the stored jobs; ``conflicts`` must be empty (they are
jobs that already exist in Link with different content; ``-f`` replaces
them). ``moat-link-job.service`` picks up ``job.any.default`` at once.
Start the other runners, on the hosts that ran their KV counterparts:

```sh
systemctl enable --now moat-link-job@dev          # any-node, group dev
systemctl enable --now moat-link-job-all          # all nodes, default group
systemctl enable --now moat-link-job-single@dev   # this host, group dev
```

Single-node runners read ``NAME`` from ``/etc/moat/link.env``; set it to
the KV node name from step 1.

## 6. Watch

```sh
moat link job at : list -t                  # per group: -g GROUP; -n - / -n NAME for the other modes
moat link job at PATH state
moat link data error.job get -r             # errors reported by the runners
journalctl -fu 'moat-link-job*'
```

``list -t`` shows each job's code and the node running it
(``-stopped-`` or ``-never-`` otherwise). Jobs that fail back off and
record their exception at ``error.job.MODE.GROUP.…``. After a day
without new errors, the cutover is done; uninstall or mask the KV
runner units.

## Rollback (from step 5 or 6)

1. Stop the Link runners: ``systemctl disable --now 'moat-link-job*'``
   (then ``systemctl enable --now moat-link-job`` again if the package
   should stay installed with an empty ``job.any.default``).
2. Remove the migrated jobs, so a runner that starts later doesn't pick
   them up: ``moat link data job delete -r`` (then restore
   ``link-jobs-before.yaml`` if it wasn't empty).
3. Start the KV runners again (step 4's rollback).

The snippets from step 3 can stay; nothing uses them without jobs.

## Known issues

* An all-node runner (``-n -``) keeps its state at
  ``run.job.all.GROUP.<connection name>``. Unless ``link.client_id`` is
  configured, the connection name is random, so every restart leaves a
  stale state subtree behind. They are harmless and can be deleted.
