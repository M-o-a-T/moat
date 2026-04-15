"""
Schema helpers for MoaT-Link payload validation.
"""

from __future__ import annotations

from jsonschema.validators import validator_for

from moat.lib.path import P, Path

from typing import Any

__all__ = [
    "Data",
    "Schema",
    "SchemaName",
    "schema_path",
    "validate_instance",
]


class Data(dict):
    "Schema-verified data (dict)."


class SchemaName(str):
    """
    Helper for building dotted schema names via attributes.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> SchemaName:
        if len(self):
            return SchemaName(f"{self}.{name}")
        return SchemaName(name)


Schema = SchemaName("")


def schema_path(path: Path) -> Path:
    """
    Return the schema lookup path for a data path.
    """
    return P("schema") + path


def validate_instance(schema: Any, data: Any) -> None:
    """
    Validate data against a JSON schema.
    """
    cls = validator_for(schema)
    cls.check_schema(schema)
    cls(schema).validate(data)
