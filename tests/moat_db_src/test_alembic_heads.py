"""The Alembic script tree must have exactly one head, or ``moat db migrate`` fails."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

import moat.db as dbmod


def test_single_head():
    "every migration branch has been merged"
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(dbmod.__path__[0]) / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, heads
