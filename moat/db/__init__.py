"""
MoaT database supprt
"""

from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
	from moat.util import attrdict

def load(*a,**kw):
	from .util import load as load_
	return load_(*a, **kw)

def database(*a,**kw):
	from .util import database as database_
	return database_(*a, **kw)
