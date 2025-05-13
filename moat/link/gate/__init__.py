"""
Gateway to wherever
"""

from __future__ import annotations

class Gate:
	def __init__(self, cfg:dict[str,Any]):
		self.cfg = cfg

	async def run(self, link:Link):
		raise NotImplementedError


def get_gate(cfg: dict, **kw) -> Gate:
    """
    Fetch the gate named in the config and initialize it.
    """
    from importlib import import_module

    name = cfg["driver"]
    if "." not in name:
        name = "moat.link.gate." + name
    return import_module(name).Gate(cfg, **kw)
