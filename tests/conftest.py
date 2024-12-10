from __future__ import annotations

import copy
import pytest
from pathlib import Path as FSPath

from moat.util import yload,merge

from moat.link._test import CFG
merge(CFG, yload(FSPath(__file__).parent.parent / "moat"/"link"/"server"/"_config.yaml", attr=True))

import logging
logging.basicConfig(level=logging.DEBUG)

@pytest.fixture
def anyio_backend():
    return "trio"


@pytest.fixture
def cfg():
    c = copy.deepcopy(CFG)
    return c
