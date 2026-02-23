# Repository Guidelines for MoaT

This file isn't just for agents …

## Issue tracking

- Use 'beads' for tracking.
  - 'bd list --label foo --ready --json': list issues
  - 'bd show --json ID': examine single issue
  - 'bd create --prio P --title TEXT --description TEXT --notes TEXT --type TYPE --labels foo,bar': create new issue
  - 'bd dep add ID-task ID-blocker': add relationship
  - 'bd update ID --parent ID --set-labels foo,bar --priority P --status S --title … --type …'
  - 'bd close --reason STRING'
  - 'bd sync': sync tracker state with git

- Conventions:
  - labels: we use "common", "doc", or "moat.xx.yy" for specific subsystems
  - status: open, in\_progress, blocked, deferred, closed
  - prio: 0…4, 0:highest
  - type: bug|feature|task|epic|chore

The purpose of issues is to remember things to do.
Thus, DO NOT create issues for one-off changes that you'd immediately close.


## Project Structure & Modules

- This is a monorepository. All code lives in `moat/`.
  - Code is CPython 13+ compatible
    - exception: code in `moat/micro/_embed` runs on a version of
      MicroPython 1.25+, enhanced with taskgroups
    - This also applies to all code which imports from `moat.lib.micro`
      (but not to moat.lib.micro itself)
    - Python 3.11 compatible syntax must be used in those parts.
  - Each Python package named e.g. `moat.X.Y` contains
    - code in `moat/X/Y/**.py`
    - `docs/moat-X-Y` for documentation
    - `packaging/moat-X-Y` for `pyproject.toml` and Debian packaging
    - `tests/moat_X_Y` for testing
    - `examples/moat-X-Y`
  - Tests use `pytest`. Required modules are listed in the global
    `pyproject.toml` and are supposed to be installed on the host system.
  - We use semantic versioning for submodules, except for major version zero.
    - Run `./mt src tag -s moat.X.Y -m` to request a new minor version; use
      `-M` for new major versions.
    - Patch versions are allocated automatically when building.
  - Shared code between CPython and MicroPython:
    - Must use `moat.lib.compat` to mask implementation differences.
    - Assume that any code that imports `moat.lib.compat` must work on
      both.
    - the MicroPython part of MoaT is in `moat/micro/_embed/lib`. It may
      use relative symlinks to refer to code in the main area.
- Build output should be created in, or moved to, the `dist/` folder.
- `packaging/**/src` is auto-populated and excluded via `.gitignore`.

## Python patterns

- A BaseException (that's not an Exception) MUST propagate.
  This includes `anyio.get_cancelled_exc_class()`.
- Use `[async] with (a,b,c)` instead of nested `[a]sync with` statements.
  - Exception: MicroPython needs a single line instead of parentheses.
    Use backslash continuation, disable reformatting for long lines.

### Typing

- MoaT does its type checking with "ty".
- Files need to be typed comprehensively, i.e. all variables,
  arguments and return types.
- Only add type:ignore comments when (a) you see an actual error from "ty",
  *and* (b) you thought hard and determined that the error cannot be fixed in
  another way.
- This also applies to `cast` expressions.
- Do not type-check function parameters. That's what `ty` is for.
- Do not range-check function parameters. It is sufficient to describe valid ranges
  in the docstring.
- After a module typechecks, add its files to the tool.ty.src.include list in
  pyproject.toml.

## Build and Test

- pre-commit enforces formatting and typechecking.
- YAML files may contain Path objects, marked with `!P`.
  The pre-commit yaml checker understands this.
- When testing, *always write the test output to a temporary file* so you
  can analyze it more easily. Running the same test multiple times is
  inefficient.

## Coding Style

- Standard Python, 4-space indents, formatted by `ruff format`.
- `ruff check` clean. See `pyproject.toml` for global exceptions.
- ignore any remaining pylint, pyright or isort comments.
  We are not using these tools any more.
  Remove these if you're changing the line anyway.
- Keep functions reasonably small. Do not repeat yourself.
- Follow existing practice when naming. Be concise.
- New modules must pass `ty check`.
- Functions and variables shall be typed concisely.

## Documentation

- Every module, class, public variable and function must be documented.
- Docstrings are written in RestructuredText, with Google-style markup for
  arguments, return values etc..
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
- Do not create enumerations like "Key features" or similar.
- Do not mention implementation details in docstrings.
- Use references, not literals.

## Testing Guidelines

- Tests should focus on exercising a module's API and its actual purpose.
- 100% coverage is a goal to aspire to, but not the main focus of our tests.
- Don't repeat tests or assertions.

## Commit & Pull Requests

- One commit per logical change.
- Mention the affected module only if a change also affects other modules.
- Every commit should test cleanly. pre-commit runs module-specific tests.
  Manually test other modules before committing if they might be affected.
- Include documentation updates with the main commit, i.e. don't commit docs
  separately.
- DO NOT include agent information, a verbose description of the change,
  etc., in commit messages. Do not repeat information that's obvious when
  looking at the diff.
- DO NOT use "--rebase" when merging or pulling.

## Agent‑Specific Notes

- You MUST follow these guidelines for any code changes in this repository.
- Do not introduce unrelated tooling or broad refactors unless specifically
  asked to do so.
- Context compaction: You MUST re-read this document after compacting.

## Completion

After editing and updating/closing issues, you MUST complete ALL steps below.
Work is NOT complete until `git push` succeeds.

### Workflow

1. **File issues for remaining work** - Create issues for anything that needs follow-up.
1. **Run quality gates** (if code changed) - Tests, linters, builds.
   "git commit" should do this automatically, via pre-commit.
1. **Commit all work**. Reference the issue(s) you worked on, if any, in
   the first line.
   Example: "Fix moat-abc: wrangled the zumblicator"
   Add a short explanation of the change if warranted, but
   DO NOT mention implementation details, esp. not if they are obvious
   when reading the changelog.
1. **Update issue status** (if you're working on one):
   Close finished work, update in-progress items.
   Include the commit ID. Example: "Fixed in COMMIT\_ID\_PREFIX".
   Don't add information to the bug that's also in the commit's text.
1. **Push to remote**:
   - run `git push`
   - If there are conflicts,
     - git pull --no-edit
     - resolve merge conflicts, if any
     - retry `git push`
     - repeat until successful
   ```
However, if a git push/pull command fails with a permission error, STOP:
the problem is a missing SSH key. The user needs to re-add the key before
you can continue.

### Mandatory Rules

- Work is NOT complete until `git push` succeeds
- If push fails, pull + resolve + retry until it succeeds
