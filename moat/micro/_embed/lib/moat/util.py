class NotGiven:
    """Placeholder value for 'no data' or 'deleted'."""

    def __new__(cls):
        return cls

    def __repr__(self):
        return "‹NotGiven›"

    def __str__(self):
        return "NotGiven"


class NoProxyError(ValueError):
    pass
