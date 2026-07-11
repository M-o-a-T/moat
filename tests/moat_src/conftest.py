"""Shared fixtures for ``moat.src`` tests.

Several tests spawn real ``git`` subprocesses against per-test repositories
in ``tmp_path``.  Pre-commit sets ``GIT_DIR`` / ``GIT_WORK_TREE`` (and
friends) in the hook environment; if those leak into the spawned git, the
``-C <repo>`` argument is ignored and git operates on the host repository
instead — corrupting its config and making the tests order-dependent.

This autouse fixture strips the inherited ``GIT_*`` variables for every
test so the subprocesses see only the per-test repository.
"""

from __future__ import annotations

import pytest

# Environment variables that pin a git repository / work-tree and would
# therefore override the per-test ``-C <repo>`` directory.
_GIT_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_QUARANTINE_PATH",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop inherited ``GIT_*`` env vars for the duration of each test."""
    for var in _GIT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
