# moat-lib-repl

% start main
% start synopsis

A straightforward async-ization of `pyrepl`.

% end synopsis

This module was copied from CPython v3.13.9 and anyio-ized.

## Usage

```python
from moat.lib.repl import multiline_input
async def main():
        inp = await multiline_input(lambda s: "\n" not in s, "=== ","--- ")
        print("RES:",repr(inp))

anyio.run(main)
```

% end main

## License

Licensed under (something like) the
[MIT License](https://github.com/python/cpython/blob/3.13/Lib/_pyrepl/__init__.py)
