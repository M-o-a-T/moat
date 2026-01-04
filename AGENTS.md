# Repository Guidelines for MoaT

This file isn't just for

## Issue tracking

- Use 'beads' for tracking.

## Project Structure & Modules

- This is a monorepository. All code lives in `moat/`.
  - Code is CPython 12+ compatible
    - exception: code in `moat/micro/_embed` runs on a version of
      MicroPython 1.25+, enhanced with taskgroups
    - This also applies to all code which imports from `moat.lib.micro`
      (but not to moat.lib.micro itself)
    - Specifically, Python 3.11 syntax must be used in these files.
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

### Typing

- MoaT does its type checking with "ty".
- Type-checked files need to be typed completely, i.e. all variables,
  arguments and return types.
- In files that import from moat.lib.micro, use explicit inheritance from
  `Generic` instead of bracket syntax.
- Only add type:ignore comments when (a) you see an actual error from "ty",
  *and* (b) you thought hard and determined that the error cannot be fixed in
  another way.
- The above also applies to `cast` expressions.
- Each type:ignore or cast requires a one-line comment explaining why the
  affected code is valid anyway.
- After a module typechecks, add its files to the tool.ty.src.include list in
  pyproject.toml.

## Build and Test

- pre-commit enforces formatting and typechecking.
- YAML files may contain Path objects, marked with `!P`.

## Coding Style

- Standard Python, 4-space indents, formatted by `ruff format`.
- `ruff check` clean. See `pyproject.toml` for global exceptions.
- while there are pyling comments in the code, we are not using it any more.
  Ignore them, or remove if you're changing the line anyway.
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
- Don't duplicate basic information: each package's `README.md` contains
  markers for a synopsis (included in `docs/index.md`) and a main part
  (included in `docs/moat-XXX-YYY/index.md`). The synopsis does not contain
  headers. The main part is assumed to be under a level 1 header. It must
  not itself contain a Level 1 header itself.

## Testing Guidelines

- Tests should focus on exercising a module's API.
- 100% coverage is a goal but not the main focus of our tests.
- Don't repeat similar tests or assertions.

## Commit & Pull Requests

- One commit per logical change.
- Mention the affected module only if a change also affects other modules.
- Every commit should test cleanly. pre-commit runs module-specific tests.
  Manually test other modules before committing if they might be affected.
- Include documentation updates with the main commit, i.e. don't commit docs
  separately.
- DO NOT include agent information, a verbose description of the change,
  etc., in commit messages.

## Agent‑Specific Notes

- You MUST follow these guidelines for any code changes in this repository.
- Do not introduce unrelated tooling or broad refactors unless specifically
  asked to do so.
- Context compaction: You MUST re-read this document after compacting.

## Completion

After editing and updating/closing issues, you MUST complete ALL steps below.
Work is NOT complete until `git push` succeeds.

### Workflow

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Push to remote** - This is MANDATORY:
   ```bash
   git pull
   resolve conflicts, if any
   bd sync
   git push
   git status  # MUST show "up to date with 'intern/main'"
   ```
5. **Verify** - All changes committed AND pushed
6. **Hand off** - Provide context for next session

If a git push/pull command fails with a permission error, STOP: the problem is a
missing SSH key. The user needs to re-add the key before you can continue.

### Mandatory Rules

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
