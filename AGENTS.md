# Repository Guidelines for MoaT

## Project Structure & Modules
- This is a monorepository. All code lives in `moat/`.
  - Code is CPython 12+ compatible
    - exception: code in `moat/micro/_embed` runs on a version of
      MicroPython 1.25+, enhanced with taskgroups
  - Each Python package named e.g. `moat.X.Y` has
    - code in `moat/X/Y/*.py`
    - `docs/moat-X-Y` for documentation
    - `packaging/moat-X-Y` for `pyproject.toml` and Debian packaging
    - `tests/moat_X_Y` for testing
    - possibly `examples/moat-X-Y`
  - Tests use `pytest`. Required modules are listed in the global
    `pyproject.toml` and are supposed to be installed on the host system.
  - We use semantic versioning for submodules, except for major version zero.
    - Run `./mt src tag -s moat.X.Y -m` to request a new minor version; use
      `-M` for new major versions.
    - Patch versions are allocated automatically when building.
  - Some code in `moat.lib` is shared between CPython and MicroPython
    areas, via symlinks.
    - Shared code must use `moat.lib.compat` to mask implementation
      differences between them.
    - Assume that any code that imports `moat.lib.compat` does run on
      both.
- Build output should be created in, or moved to, the `dist/` folder.

## Python patterns
- A BaseException (that's not an Exception) MUST propagate.
  This includes `anyio.get_cancelled_exc_class()`.
- Use `async with (a,b,c)` instead of nested `async with` statements.

## Build and Test
- pre-commit enforces formatting and typechecking.
- YAML files may contain Path objects, marked with `!P`.

## Coding Style
- Standard Python, 4-space indents, formatted by `ruff format`.
- `ruff check` clean. See `pyproject.toml` for global exceptions.
- Keep functions reasonably small. Do not repeat yourself.
- Follow existing practice when naming. Be concise.
- In legacy code, these guidelines are aspirational:
  - All code should be pyright clean.
  - Functions and variables shall be typed concisely.

## Documentation
- Every module, class, public variable and function must be documented.
- Docstrings are written in RestructuredText, with Google-style docstrings.
- Types are specified in the function declaration, not in the docstring.
  - Legacy code might use something wildly different. Don't copy legacy
    styles! Always use / convert to Google style and proper object
    references for new or updated code, or when instructed to fix
    documentation.
- All other documentation is written using Markdown (Myst).
  Only use RestructuredText syntax or blocks when Myst doesn't support a
  feature.

## Testing Guidelines
- Tests should focus on exercising a module's API.
- Don't repeat similar tests or assertions.

## Commit & Pull Requests
- One commit per logical change.
- Mention the affected module only if a change also affects other modules.
- Every commit should test cleanly. pre-commit runs module-specific tests.
  Manually test other modules before committing if they might be affected.
- Include documentation updates with the main commit, i.e. don't commit docs
  separately.
- Don't include agent information, a verbose description of the change,
  etc., in commit messages.

## Agent‑Specific Notes
- Follow these guidelines for any code changes in this repo tree.
- Do not introduce unrelated tooling or broad refactors unless specifically
  asked to do so.
