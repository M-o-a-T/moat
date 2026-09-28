# Code snippets, and testing them

Epic: `moat-zshv` in Beads.

`./mt kv job` runs a number of tasks that are, obviously, MoaT-KV based.
We need to move them to `moat.link` and its job handling
(`moat link job`, `moat/link/job/`).

Problem: the code may need updates and is basically untested.

## Where we are (surveyed 2026-09-28)

- MoaT-KV runs about 60 jobs in the `default` group (any node), using 25
  different code snippets: `transform.copy.value` (7 jobs),
  `timer.auto_off` (5), `mqtt.read.num` (5), `transform.copy.bool`,
  `timer.float_avg`, `mqtt.write.bool` (4 each), `transform.multi.{sum,or}`,
  `transform.hysteresis` (3 each), and a dozen used once or twice
  (`transform.{toggle,timeslot,scale,lookup,hysteresis.delta,switch,
  short-long,path.flags,distribute,copy.multi}`, `transform.multi.{min,max,and}`,
  `step.brightness`, `mqtt.read.bool`, `keepalive.monitor`). There are also
  `dev` and `debug` groups and all-node jobs.
- 29 snippets have already been copied into MoaT-Link (`code.*`,
  `moat link code`), unchanged. They still use the MoaT-KV job API:
  53 × `_client.set(…, idem=True)`, 3 × `_client.get`. The Link job
  runner has no `_client`; it passes `_link` (a `LinkSender`) and `_self`
  (a `CallAdmin`: `watch`, `monitor`, `timer`, `set`, `get`, `send`,
  `setup_done`, …). So these snippets fail in the Link runner as they
  are.
- `moat link job … debug` (`moat.link.job.runner.debug_run`) runs one
  stored job interactively; it is the natural base for running code
  under test.
- `moat.lib.path` has a `:T` root (a context variable, like `:R`) for
  tests. Link client calls reject root-prefixed paths.

## Goals

1. Every snippet that production uses has test cases stored next to it,
   and passes them in the Link job runner.
2. Test cases are easy to write and edit from the command line.
3. Tests run in parallel, against a live server, without touching
   production data.
4. The MoaT-KV jobs are then migrated to `moat link job`, and the KV job
   runner is switched off.

## Test cases

### Storage

A snippet lives at `code.PATH.TO.NAME`. Its test cases live at
`code.PATH.TO.NAME:n.TEST.CASE` — the `None` element (`:n`) separates
the snippet from its tests, as snippets can have children
(`transform.hysteresis` and `transform.hysteresis.delta`).

A test case is one item, validated by a pydantic model:

```yaml
info: short description
timeout: 10          # seconds for the whole test; default 30
data:                # initial MoaT-Link data below :T, like `moat link data … get -rd_`
  in:
    _: 1
  out:
    _: 0
args:                # the job's `data` (the snippet's parameters)
  src: !P in         # unrooted paths: below :T
  dst: !P out
  seconds: 0.2
steps:               # the actions, in order (see below)
- [monitor, out, !P out]
- [start]
- [set, !P in, 2]
- [wait, 1, "out[-1] == 2"]
- [check, "len(out) == 2"]
```

`moat link code list` and friends must skip the `:n` subtrees; the job
runner's code-change watcher only watches the snippet itself, so test
edits don't restart running jobs.

### Paths

- Every unrooted path in `data`, `args` and `steps` is below the test
  root `:T`; `:R.…` is an absolute path in the tree.
- A test run sets `:T` to `:R.test:PID:SEQ` (PID of the runner, SEQ a
  counter), so parallel tests don't collide.
- The runner resolves all paths before they reach the snippet or the
  Link client: `:T`-relative ones get the test root prepended, `:R` ones
  lose the root marker. The snippet itself sees ordinary paths and
  needs no test awareness.
- After the test, the test root is deleted (`d.delete(rec=True)`), even
  if the test failed; `--keep` skips that for debugging.

### Actions

Stored as lists (`[verb, arg, …]`); the editor shows one per line
(below). Values use the syntax of `moat link data PATH set -s KEY VALUE`
(`~str`, `=expr`, `.path`, …), expressions are evaluated with
`moat.lib.run`'s restricted evaluator (`simpleeval`), with the monitors
(see below), `P`, `len`, `abs`, `min`, `max` available.

| Action | Meaning |
| --- | --- |
| `start` | Start the snippet as a job with `args`. Implicit before the first action that isn't `monitor`/`comment` if missing. |
| `set PATH VALUE` | `d_set(PATH, VALUE)` (retained). |
| `update PATH KEY VALUE …` | Read-modify-write like `moat link data PATH set -s KEY VALUE …`. |
| `delete PATH` | Delete the item. |
| `send PATH VALUE [CODEC]` | Raw MQTT message (not retained), for snippets that `_self.monitor` MQTT topics; default codec `std-cbor`. |
| `monitor NAME PATH [mqtt [CODEC]]` | Start collecting the values seen at PATH (or raw MQTT messages) into the list `NAME`; `NAME[-1]` is the latest. Starts with the current value unless `mqtt`. |
| `wait TIMEOUT [EXPR]` | Sleep TIMEOUT seconds, or until EXPR is true (re-evaluated whenever a monitor receives something); fail on timeout if EXPR is given. |
| `check EXPR` | Fail unless EXPR is true. |
| `sleep SECONDS` | Wait unconditionally (sugar for `wait` without EXPR). |
| `result [EXPR]` | Wait (up to the test timeout) for the snippet to end; `result` is its return value; fail if it raised, or EXPR is false. |
| `error [EXPR]` | Wait for the snippet to fail; `error` is the exception. |
| `comment TEXT` | Nothing; shown in the log. |

A test passes when all actions succeed and the snippet has not raised
(unless `error` expected it). At the end the snippet is cancelled.

### Running the code

The snippet runs exactly as under `moat link job run`: a `JobEntry` /
`CallAdmin` built as `debug_run` does it, with `_self`, `_link`, `_info`,
`_cls`, `_log`, … and the job's `data` from `args`. `debug_run` gets
refactored so that the job record and state are passed in rather than
read from the job tree (the state goes below `:T`), and so that it
returns the running task's outcome to the test.

Time is real (the server is a real one); tests use short timeouts and
delays in their `args`.

### Editor format

`moat link code PATH test CASE edit` opens an editor with the header as
one YAML document (`info`, `timeout`, `data`, `args`), a `---` line, and
then one action per line: the verb, then its arguments separated by
spaces, values in the `set -s` syntax, `#` starting a comment line
(stored as `comment`). An expression is the rest of the line. Saving
parses it back into the structured form; a syntax error re-opens the
editor, as `moat link data … edit` does.

## Command line

Below `moat link code PATH` (`moat/link/code/_main.py`):

- `test` — list the snippet's test cases.
- `test CASE get` / `set -d FILE` / `edit` / `delete`.
- `test CASE run [--keep] [-v]` — run one test; exit code 1 on failure.
- `test - run` — run all of the snippet's tests, in parallel.
- `moat link code : test-all [-j N]` — run the tests of every snippet;
  a summary per snippet, non-zero exit if anything failed.

## Porting the snippets

For each of the 25 snippets used in production:

1. Replace the MoaT-KV API: `_client.set(p, value=v, idem=True)` →
   `_self.set(p, v)` (idempotent writes: `Writer`-like cache in
   `CallAdmin`, or compare with the last value in the snippet),
   `_client.get(p)` → `await _self.get(p)`.
2. Write test cases covering the snippet's documented behaviour
   (at least one per parameter combination used in production).
3. Fix whatever the tests find.

The snippets that no job uses (`test.sleep`, `timer.float_avg.debug`, …)
are deleted or moved to `code.old`.

## Migrating the jobs

1. A converter reads the MoaT-KV job records (and their groups/nodes) and
   writes `job.any.GROUP.…` / `job.at.NODE.GROUP.…` / `job.all.GROUP.…`
   records, mapping the fields (`code`, `data`, `delay`, `repeat`,
   `ok_after`, `backoff`, `target`, `info`); dry run by default, like
   `moat db inv migrate-from-kv`.
2. Paths in job `data` that pointed at MoaT-KV-only trees are checked
   against Link (report, don't guess).
3. Cutover: stop `moat kv job run`, start `moat link job run` for the
   same groups; watch the jobs' state and the error tree.

## Open questions

- Should the test cases also be kept in the repository (e.g. exported
  to `examples/moat-link/code/`) and run by pytest against a Scaffold
  server, or do they live only in the production Link tree?
- `idem=True`: give `CallAdmin.set` an `idem` flag (as MoaT-KV had), or
  change the snippets to compare themselves?
- Keep a compatibility `_client` in the Link runner for a transition
  period, or port all snippets before the cutover (plan above)?
