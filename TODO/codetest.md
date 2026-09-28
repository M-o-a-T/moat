# Code snippets, and testing them

"./mt kv job" contains a number of tasks that, obviously, are
moat-kv-based. We need to transfer them to moat.link and its job handling.

Problem: the code may need updates and is basically untested.

## Test handling

Existing: Code is stored in moat.link as code.PATH.TO.NAME

New: We store testcases in code.PATH.TO.NAME:n.TEST.CASE

Tests contain
- initial moat-link data, stored like the output of "moat link data XX get -rd_"
- inputs to the code. Paths shall use :T as a test root
- a sequence of actions to take, e.g.
  - set PATH VALUE
  - update PATH [KEY VALUE]… # interpreted as in 'moat link data PATH set -s KEY VALUE'
  - comment TEXT

  We also need functions to start monitoring a path for changes:
  - monitor NAME PATH
  - check EXPR  # NAME is a global with the array of messages the NAME monitor received
  - wait TIMEOUT [EXPR] # wait, monitoring NAME, until TIMEOUT or EXPR is True

  and probably some others, like access to MQTT messages with encodings.

## Command line

`moat link code PATH.TO.NAME test TEST.CASE`

with commands like list/set/run; "test - run" processes all testcases.

The editor should present the testcase as an initial YAML document, followed by
plain lines that describe the actions, leading `#` as "comment". Storage
should be structured.

All unrooted paths should be based on :T; a testcase may explicitly use :R.

## Test running

Test runs should set :T to :R.test:PID:SEQ. Multiple tests should run in
parallel.
