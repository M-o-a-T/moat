"""
Base model for
"""

from __future__ import annotations

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict
from pydantic.fields import FieldInfo
from pydantic_variants.core import DecomposedModel

from typing import Any


class BaseModel(_BaseModel):
    """
    A BaseModel that accepts field updates.
    """

    model_config = ConfigDict(extra="allow", validate_assignment=True, strict=True)

    @classmethod
    def add_field_(cls, name: str, annotation: object, **kw: Any) -> None:
        """
        Add a Pydantic

        Args:
            name: Field name.
            annotation: Python type.

        ``annotation`` as well as any other arguments are forwarded to
        `pydantic.FieldInfo`.
        """
        dec = DecomposedModel(cls)
        dec.model_fields[name] = FieldInfo(annotation=annotation, **kw)
        ncls = dec.build(cls.__name__, cls)
        for k, v in vars(ncls).items():
            setattr(cls, k, v)

    def __getattr__(self, k: str) -> Any:
        """
        Attribute fetch that pydantic-izes extra data if the class is
        extended later on.
        """
        if not k.startswith("_"):
            extra = self.__pydantic_extra__
            if extra is not None and k in extra and k in type(self).__pydantic_fields__:
                super().__setattr__(k, extra.pop(k))
                return vars(self)[k]

        get_attr = getattr(_BaseModel, "__getattr__", None)
        if get_attr is not None:
            return get_attr(self, k)
        raise AttributeError(k)
