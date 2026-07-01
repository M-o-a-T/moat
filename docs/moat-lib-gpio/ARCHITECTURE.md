# Architecture — moat.lib.gpio

Linux GPIO character-device (`/dev/gpiochip*`) abstraction.

## Implementation (`gpio/_impl.py`)

- **`Chip`** — represents one GPIO chip; opened via `open_chip()`.
- **`Line`** — a single GPIO line.
- **`LineSettings`** — direction/drive/edge/bias/debounce configuration.
- Enums: direction, drive, edge, bias.

Uses the kernel **GPIO characterdev** uAPI (not the deprecated sysfs
`/sys/class/gpio`), so it supports bias, debounce, and simultaneous
multi-line requests.

## Consumers

Primarily the MicroPython/embedded side via `moat.micro.part.pin` for
on-device GPIO, and host-side tooling needing direct Linux GPIO access. On
MicroPython hardware the native `machine.Pin` is used instead; `moat.lib.micro`
papers over the difference for shared code paths.
