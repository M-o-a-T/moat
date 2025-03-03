"""
MoaT database supprt
"""

from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
	from moat.util import attrdict

def load(cfg: attrdict):
	from .util import load as load_
	load_(cfg)
