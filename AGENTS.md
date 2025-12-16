# Repository Guidelines for MoaT

## Project Structure & Modules
- This is a monorepository. All code lives in `moat/`.
  - Code is CPython 12+ compatible
    - exception: `moat/micro/embed` runs on MicroPython 1.25+
  - Each Python module named `moat.XXX.YYY` has
    - `docs/moat-X-Y` for documentation
    - `packaging/moat-X-Y` for `pyproject.toml` and Debian packaging
    - `tests/moat_X_Y` for testing
  - Tests use `pytest`. Required modules are supposed to be installed on the host.
  - We use semantic versioning for submodules.
    - Run `./mt src tag -s moat.X.Y -m` to request a new minor version; use
      `-M` for new major versions.
- Build output should be created in, or moved to, `dist/`.

## Build and Test
- pre-commit enforces formatting and typechecking.
- YAML files may contain Path objects, marked with `!P`.

## Coding Style
- Standard Python, 4-space indents, formatted by `ruff format`.
- `ruff check` clean. See `pyproject.toml` for exceptions.
- Keep functions reasonably small. Do not repeat yourself.
- Follow existing practice when naming. Be concise.
- This is a legacy codebase. The following guidelines are aspirational:
  - All code should be pyright clean.
  - Functions and variables shall be typed concisely.

## Documentation
- Every module, class, public variable and function must be documented.
- All documentation is written using Markdown (Myst).
  Do not use RestructuredText syntax.
- We use Google-style docstrings. Types are specified in the function
  declaration, not in the docstring.
  - Legacy code might use something wildly different. Don't copy legacy
    styles! Always use / convert to Google style and Myst references for
    new or updated code, or when instructed to fix documentation.

## Testing Guidelines
- Tests focus on exercising a module's API
- don't repeat similar tests or assertions

## Commit & Pull Requests
- One commit per logical change
- Mention the affected module only if a change also affects other modules
- Every commit should test cleanly
- Include documentation updates with the main commit

## Agent‑Specific Notes
- Follow these guidelines for any code changes in this repo tree.
- Do not introduce unrelated tooling or broad refactors in a single PR.
