# MoaT-Lib-PrioMap

% start synopsis

A heap that behaves like a dict (or vice versa).

The keys are ordered by their associated value.

% end synopsis

## Features

* Dictionary-style access:

  * `h[key] = priority` (insert/update)
  * `prio = h[key]` (lookup)
  * `del h[key]` (remove)

* Bulk initialization: `PrioMap({'a':1, 'b':2})`

* Priority operations:

  * `h.popitem()` & `h.peekitem()` for root (min)
  * `h.update(key, new_prio)` to change an existing key’s priority

* Introspection:

  * `len(h)`, `key in h`, `h.is_empty()`

* Safe iteration:

  * `.keys()`, `.values()`, `.items()`, and plain `for k, v in h:`

  * Detects concurrent modifications and raises `RuntimeError`.

### Non-Features

* Storing more than the priority.
  Workaround: use a `(prio, other_data)` tuple.

* Sorting by highest instead of lowest priority first.
  Workaround: store the negative priority value.


## Installation

```bash
pip install moat-lib-priomap
```

## Usage

### PrioMap

```python
from moat.lib.priomap import PrioMap

# Min-heap example
h = PrioMap({'a':5, 'b':2, 'c':3})
print(h.peekitem())  # ('b', 2)

# Insert
h['d'] = 1
print(h.popitem())   # ('d', 1)

# Update
h.update('a', 0)
print(h.peekitem())  # ('a', 0)

# Iterate. Does not consume the data.
for key, prio in h.items():  # keys(), values()
    print(f"{key} -> {prio}")
# emits a->0, d->1, b->2, c->3

# Async Iteration. Does consume the data!
# Waits for more data if/when it runs out.
async for key, prio in h:
    print(f"{key} -> {prio}")

```

### TimerMap

```python
from moat.lib.priomap import TimerMap

# example
h = TimerMap({'a':5, 'b':2, 'c':3})
print(h.peekitem())  # ('b', 1.995)

# Iterate
async for key in h:
    print(key)
# > waits two seconds
# b
# > waits another second
# c
# > two seconds later
# a
```


## License

MIT.
