"""
Simple relay control.
"""

import machine as M

from moat.util import NotGiven, load_from_cfg, attrdict

class Relay:
    """
    A relay is an output pin with an overriding "force" state.
    """
    def __init__(self, cfg, value=None, force=None, **kw):
        pin = cfg.pin
        if isinstance(pin,int):
            cfg.pin = attrdict(client="app.part.pin.Pin", pin=pin)
        kw.setdefault(mode, M.Pin.OUT)
        self.pin = load_from_cfg(cfg.pin, **kw)

        if value is None:
            value = self.pin.value()
        self.value = value
        self.force = force
        self.set()

    def set(self, value=None, force=NotGiven):
        """
        Change relay state.

        The state is set to @force, or @value if @force is None,
        or self.value if @value is None too.

        If you don't pass a @force argument in, the forcing state of the
        relay is not changed.
        """
        if value is not None:
            self.value = value
        if force is NotGiven:
            if self.force is not None:
                return
            if value is not None:
                self.value = value
                self.pin.value(value)
        else:
            self.force = force
            if force is None:
                self.pin.value(force)
            else:
                self.pin.value(self.value)

    def get(self):
        """
        Return the current intended state.
        """
        if self.force is not None:
            return self.force
        return self.value

    def state(self):
        return dict(s=self.value, f=self.force)
