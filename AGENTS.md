# Repository Guidelines for MoaT

This file isn't just for agents …

## Issue tracking

- Use 'beads' for tracking.
  - 'bd list --label foo --ready --json': list issues
  - 'bd show --json ID': examine single issue
  - 'bd create --priority P --title TEXT --description TEXT --notes TEXT --type TYPE --labels foo,bar': create new issue
  - 'bd dep add ID-task ID-blocker': add relationship
  - 'bd update ID --parent ID --set-labels foo,bar --priority P --status S --title … --type …'
  - 'bd close --reason STRING'

- Conventions:
  - labels: we use "common", "doc", or "moat.xx.yy" for specific subsystems
  - status: open, in\_progress, blocked, deferred, closed
  - prio: 0…4, 0:highest
  - type: bug|feature|task|epic|chore

The purpose of issues is to remember things to do.
Thus, DO NOT create issues for one-off changes that you'd immediately close.

## API documentation

You can use the ty language server, or read build/specs/moat-xxx/api.md.

If you need details that are not documented, you may read the actual code,
but then *create an issue* detailing what's missing to improve the docs later.

## Project Structure & Modules

- This is a monorepository with submodules. All code lives in `moat/`.
  - Code is CPython 13+ compatible
    - exception: code in `moat/micro/_embed` runs on a version of
      MicroPython 1.25+, enhanced with taskgroups
    - This also applies to all code which imports from `moat.lib.micro`
      (but not to moat.lib.micro itself)
    - Python 3.11 compatible syntax must be used in those parts.
    - moat.web uses Ludic, thus requires Python 3.14.
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

- MoaT uses anyio for async code. Never import from asyncio.

- NEVER busy-loop. NEVER delay to get something to work (except in testcases).

- A BaseException (that's not an Exception) MUST be re-raised.
  This includes `anyio.get_cancelled_exc_class()`.

- In `moat.lib` and `moat.micro`, do not use syntax that doesn't work with
  MicroPython. Specifically:
  - `(foo,bar,*baz)` list expansion
  - `with (x,y)`
  - def foo(bar,/) positional-only arguments
  - Python 3.12+ syntax for generic types
  - `isinstance(obj, type1 | type2)` -- use `isinstance(obj, (type1 type2))`
  - multiple inheritance (syntax works but is ignored)
  - micropython doesn't have anyio, but we do not directly import from
    asyncio either. Always use the compatibility code in moat.micro.compat.

- Prefer to import from moat.lib.XX, moat.link.XX, or moat.YY modules, not
  from submodules. Exception: `TYPE_CHECKING` blocks.

### Typing

- MoaT does its type checking with "ty".
- Use "ty check --output-format github" if you need to fix typing errors.
- Files need to be typed comprehensively, i.e. all variables,
  arguments and return types.
- DO NOT type:ignore comments, use the "Any" type, or add casts.
  UNLESS (a) you see an actual error from "ty", *and* (b) you THOUGHT HARD
  and determined that the error CANNOT be fixed some another way.
- Do not type-check data explicitly. That's what `ty` is for.  If that's
  not possible, duck typing (or the failure thereof) will raise a `TypeError`.
- Do not range-check function parameters. It is sufficient to describe valid ranges
  in the docstring.
- DO NOT replace "def foo() -> Awaitable[Bar]: return asyncfn()" with an async
  def. The correct type is `CoroutineType[Any,Any,Bar]`.
- After a module typechecks, add its files to the tool.ty.src.include list in
  pyproject.toml.

## Build and Test

- pre-commit enforces testing, formatting and typechecking.
  DO NOT run formatters or type checkers on your own, except when you're fixing
  an error.
- YAML files may contain Path objects, marked with `!P`.
  The pre-commit YAML checker understands this.
- When testing, *always write the test output to a temporary file* so you
  can analyze it more easily. Running the same test multiple times is
  inefficient.

## Coding Style

- Standard Python, 4-space indents, formatted by `ruff format`.
- `ruff check` clean. See `pyproject.toml` for global exceptions.
- ignore pylint, pyright or isort comments.
  Remove them if you're changing the line anyway.
- Keep functions reasonably small.
- Do not repeat yourself. Use subclassing.
- Follow existing practice when naming. Be concise.
- New modules must pass `ty check`.
- Functions and variables shall be typed concisely.

## Documentation

- Every module, class, public variable and function must be documented.
- Docstrings are written in RestructuredText, with Google-style markup for
  arguments, return values etc..
- Types are specified in the function declaration, not in the docstring.
  - Legacy code might use something different. Don't copy legacy styles!
    Always use / convert to Google style and proper object references for
    new or updated code, or when instructed to fix documentation.
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
- DO NOT use "head", "tail", or "rg" / "grep" on test output.
  Instead, redirect to a temp file (or check tmux content) and post-process that.
- moat.src.test contains wrappers "run" (process a `moat ...` command line)
  and `raises` (like pytest.raises but ignores exception groups).

## Commit & Pull Requests

- One commit per logical change.
- Mention the affected module only if a change also affects other modules.
- Every commit should test cleanly. pre-commit runs module-specific tests.
  Manually test other modules before committing if they might be affected.
- Include documentation updates with the main commit.
  Do not commit docs separately.
- DO NOT include agent information, a verbose description of the change,
  etc., in commit messages. Do not repeat information that's obvious when
  looking at the diff.
- DO NOT use "--rebase" when merging or pulling.
- DO NOT use "--no-verify" when committing.
  - If you encounter a pre-existing failure, temporarily stash your changes
    and run a sub-agent to fix the problem.

## Agent‑Specific Notes

- Do not introduce unrelated tooling or refactors unless specifically
  asked to do so.
- Context compaction: You MUST re-read this document after compacting.
- DO NOT use "grep -r" or similar commands on the whole repository.
  Always use "git grep". Likewise, use "git ls-files | grep ...", not "find .".
- If you need a command or tool that's not currently available: DO NOT
  scan the system's directory tree. DO NOT try to install it. DO NOT
  try to find a workaround. Instead, ask the user.

# Issue Processing

This section only applies when resolving a Beads issue.

## Completion

After editing and updating/closing issues, you MUST complete ALL steps below.
Work is NOT complete until `git push` succeeds.

### Workflow

1. **File issues for remaining work** - Create issues for anything that needs follow-up.
1. "git commit" runs quality gates automatically. If errors are reported,
   fix and resubmit.
1. **Commit all work**. Reference the issue(s) you worked on, if any, in
   the first line.
   Example: "Fix moat-abc: wrangled the zumblicator"
   Add a short explanation of the change if warranted, but
   DO NOT mention implementation details, esp. not if they are obvious
   when reading the diff.
1. **Update issue status** (if you're working on one):
   Close finished work, update in-progress items.
   Include the commit ID. Example: "Fixed in COMMIT\_ID\_PREFIX".
   Don't add information to the bug that's also in the commit's text.
1. **Push to remote**:
   - run `git push intern HEAD:main`
   - If there are conflicts,
     - git pull --no-edit
     - resolve merge conflicts, if any
     - retry `git push`
     - repeat until successful
   ```
However, if a git push/pull command fails with a permission error, STOP:
the problem is a missing SSH key. The user needs to re-add the key before
you can continue.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
