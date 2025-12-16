# moat-lib-gpio: GPIO access via anyio and libgpiod

MoaT-lib-GPIO is a simple wrapper around `libgpiod`.

You can use MoaT-lib-GPIO to \* access a GPIO chip \* get an object
describing a GPIO line \* open the line for input or output \* monitor
the line for events (without polling!)

MoaT-lib-GPIO only supports Linux. It uses the "new" GPIO interface,
i.e. kernel 4.5 or later is required.

<div class="toctree" maxdepth="2">

usage.rst history.rst

</div>

# Indices and tables

- `genindex`
- `modindex`
- `search`
- `glossary`
