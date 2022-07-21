class NotGiven:
    """Placeholder value for 'no data' or 'deleted'."""

    def __new__(cls):
        return cls

    def __repr__(self):
        return "‹NotGiven›"

    def __str__(self):
        return "NotGiven"


class Proxy:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.name)})"


from ._merge import merge

