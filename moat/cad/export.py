"""
Export helpers.
"""
from __future__ import annotations

import cadquery as cq
from pathlib import Path

__all__ = []


def _export(self, filename):
    cq.Assembly(name=Path(filename).stem).add(self).save(
        filename,
        cq.exporters.ExportTypes.STEP,
        mode=cq.exporters.assembly.ExportModes.FUSED,
    )
    return self

cq.Workplane.export = _export
