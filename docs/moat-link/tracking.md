# App tracking

In a distributed system you might want to know which applications are
running where (or, more importantly not running). Also, you might want
to talk to that app directly, rather than via MQTT messaging.

MoaT-Link has two mechanisms to help with this task.

## Liveness tracker

When a MoaT Link is opened, a retained message is posted to the
`:R.run.id.RANDID` topic. `RANDID` is a random client-generated ID. The
message contains the host name, pid, and the program's name and arguments.

The client will also post a message to `:R.run.ping.id.RANDID` every few
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

If the program accepts RPC commands, a `path` element points to the service
endpoint.

Programs may register multiple and more-or-less-independent host endpoints.
An endpoint must monitor the `run.host.PATH` topic. If the entry is supplanted,
i.e. the ID changes or the message is deleted, the endpoint must terminate
immediately.

## Cleanup

Deleting stale retained ID and Host messages is the job of the `moat-link-host`
service on the main system. The identity of the main system is currently
configured statically.

The `run.id.RANDID` message shall be deleted after the `timeout.ping.timeout`
timer expires. Service messages will persist for `timeout.ping.service`
seconds. In order to avoid race conditions, the cleanup service shall block
such deletions for `timeout.ping.delay` seconds after any new `run.id.*`
message is received.

## State Transitions

A program's service is considered to be "up" if

* at least one run.ping.id.RANDID message was seen
* the last received ping contains `up=True`
* the `run.id.RANDID` message exists
* the `run.host.SERVICE` message exists (and contains `id=RANDID`)

Starting programs must send their `run.id.RANDID` message before checking
whether the service(s) they offer are still live; this should leave ample
time for avoiding replace/delete collisions.

### Errors

Error records shall be generated (via
{py:meth}`~moat.link.client.Link.e_info`) for `run.host.XXX` entries when
* the associated program goes down / disappears, and doesn't come back up
  after `timeout.restart.error` seconds
* the program doesn't transition to `up=True` within `timeout.restart.up`
  seconds
* the program restarts again (i.e. the `run.host.XXX` message is
  republished with a different ID), within `timeout.restart.flap` seconds.

Errors shall be resolved ({py:meth}`~moat.link.client.Link.e_ok`) when the
program has been up for at least `timeout.restart.up` seconds (single
restart), or `timeout.restart.flap` seconds (multiple restarts within
`timeout.restart.flap` seconds).
