# Architecture — moat.lib.priomap

Priority-ordered map: a helper for priority-scheduled dispatch.

## Implementation (`priomap/_impl.py`)

A mapping that orders entries by assigned priority (lower number = higher
priority) and supports efficient iteration in priority order. Used where a
set of handlers/tasks must be visited in a deterministic, priority-ranked
sequence rather than insertion order.

## Consumers

An internal scheduling helper used by dispatch/monitoring paths that need
ordered traversal of registered items (e.g. prioritized message handlers or
sensor poll ordering). Narrow scope; few direct dependents.
