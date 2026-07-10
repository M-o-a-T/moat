# Architecture — moat.api

Thin Python wrappers around vendor C libraries (loaded via CFFI), providing
async-friendly interfaces to hardware sensors (`api/__init__.py:1`).

## Key types

- **`DLL(id, cdef, *paths)`** (`_dll.py:43`) — a refcounted, thread-safe
  `cffi.dlopen()` context manager. Caches loaded libraries by ID; closes them
  when the last user exits. Used by all C-library-backed drivers.
- **`moat.api.bosch.bmv080`** (`bosch/bmv080.py`) — complete CFFI wrapper for
  the Bosch BMV080 particulate-matter sensor (PM1/PM2.5/PM10). Exports
  `BMV080`, `BMV080Error`, `BMV080Output`, `DutyCyclingMode`,
  `MeasurementAlgorithm`, `StatusCode`. Enforces library version bounds
  (`_MIN_VERSION`, `_MAX_VERSION`).

## Integration

Drivers under `moat.dev` use these wrappers to talk to physical hardware. The
`DLL` mechanism ensures shared native libraries aren't loaded/closed
repeatedly. Both `__init__.py` files use `pkgutil.extend_path` for
namespace-package style extension.

## Entry points

Library-style — instantiate the wrapped class (e.g. `BMV080(…)`) and call its
methods. No dedicated CLI.
