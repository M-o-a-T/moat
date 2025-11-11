# App tracking

In a distributed system you might want to know which applications are
running where (or, more importantly not running). Also, you might want
to talk to that app directly, rather than via MQTT messaging.

MoaT-Link has two mechanisms to help with this task.

## Liveness tracker

When a MoaT Link is opened, a retained message is posted to the
`:R.run.id.RANDID` topic. `RANDID` is a random ID. The message contains the
host name, pid, and the program's name and arguments.

The program will also post a message to `:R.run.ping.id.RANDID` every few
seconds (the interval is configurable). The message should contain a map:

* up
  A bool flag noting whether the program is still operating. If False,
  it is not. The link will also register a MQTT Will message to that
  effect.

* state
  A string for human consumption. It is set to "init" on startup and to
  "auto" if the program has been running for a few seconds.

## Service tracking

Programs that depend on uniqueness (as in, only one copy should be running)
register themselves by posting a message to `run.host.PATH` which, at
minimum, contains their ID (in an `id` map element, unsurprisingly).

If the program offers a service, a `path` element points to their service
endpoint.

Programs may register multiple and more-or-less-independent host endpoints.
They must monitor the `run.host.PATH` topic and should terminate if supplanted.

## Cleanup

Deleting the retained ID and Host messages is the job of the `moat-link-host`
service on the main system. The identity of the main system is currently
configured statically.

The sole condition for clean-up is that no more Ping messages arrive.
