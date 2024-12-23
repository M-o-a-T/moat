"""
Export helpers.
"""

from __future__ import annotations

try:
    import cadquery as cq
except ImportError:
    cq = None
from pathlib import Path

__all__ = []


if cq is not None:

    def _export(self, filename):
        cq.Assembly(name=Path(filename).stem).add(self).save(
            filename,
            cq.exporters.ExportTypes.STEP,
            mode=cq.exporters.assembly.ExportModes.FUSED,
        )
        return self

    cq.Workplane.export = _export
