# noqa:D100
from __future__ import annotations

from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase, declared_attr

from moat.util import NotGiven

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class Base(DeclarativeBase):
    """Base class which provides automated table name
    and surrogate primary key column.

    """

    @declared_attr.directive
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(Integer, primary_key=True)

    def dump(self) -> dict[str, Any]:  # noqa:D102
        res = dict()
        for k in self.__table__.c:
            if k.name == "id" or k.name.endswith("_id"):
                continue
            v = getattr(self, k.name)
            if v is not None:
                res[k.name] = v
        return res

    def apply(self, **kw) -> None:  # noqa:D102
        for k, v in kw.items():
            if v is NotGiven:
                continue
            setattr(self, k, v)
