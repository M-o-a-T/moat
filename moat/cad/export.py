"""
Export helpers.
"""

from __future__ import annotations

from pathlib import Path

try:
    import cadquery as cq
    from cadquery.occ_impl.exporters import assembly as cqa
except ImportError:
    cq = None  # ty:ignore[invalid-assignment,misc]  # optional import

__all__: list[str] = []


if cq is not None:

    def _export(self: cq.Workplane, filename: str | Path) -> cq.Workplane:
        """Add this Workplane to an Assembly and save as STEP."""
        cq.Assembly(name=Path(filename).stem).add(self).save(
            str(filename),
            cq.exporters.ExportTypes.STEP,
            mode=cqa.ExportModes.FUSED,
        )
        return self

    cq.Workplane.export = _export  # ty:ignore[invalid-assignment]
