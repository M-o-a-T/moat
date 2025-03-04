from __future__ import annotations

from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase, declared_attr

class Base(DeclarativeBase):
    """Base class which provides automated table name
    and surrogate primary key column.

    """

    @declared_attr.directive
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(Integer, primary_key=True)


    def dump(self):
        res = dict()
        for k in self.__table__.c:
            v = getattr(self, k.name)
            if v is not None:
                res[k.name] = v
        return res

