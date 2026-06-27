"""
PID controller.
"""

from __future__ import annotations

from moat.lib.broadcast import Broadcaster
from moat.lib.micro import AC_use, TaskGroup
from moat.lib.path import Path
from moat.lib.pid import CPID
from moat.lib.rpc import BaseCmd

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import Msg, MsgSender

_state_d = dict(t="int:last time", e="float:error", i="float:integral")
_pid_d = dict(p="float:P", i="float:I", d="float:D", tf="float:Filter D")


class PID(BaseCmd):
    """
    A PID controller periodically (we hope) receives an input value, and
    returns an output to adjust the input.

    - min, max: output value boundaries
    - p: proportional gain
    - i: integral gain
    - d: differential gain
    - tf: first-order filter time constant for the differential, in seconds
    - state: path to our state storage
    - set: initial goal (default zero)

    t should be larger than the interval between inputs.
    """

    pid: CPID
    val_in: float | None = None
    split: tuple[float, float, float] | None = None
    state_path: Path | None = None
    state_rtc: MsgSender | None = None
    _locked: bool = False
    _lock_up: bool | None = None
    _lock_i: float = 0.0

    doc = dict(
        _c=dict(
            _d="PID control",
            state=dict(_d="initial state", **_state_d),
            factor="float:setpoint adj factor (0)",
            offset="float:setpoint adj offset (0)",
            setpoint="float:initial goal",
            **_pid_d,
        )
    )

    def __init__(self, cfg):
        super().__init__(cfg)
        self.pid = CPID(cfg)
        self.state_path = cfg.get("state", None)
        self.pid.setpoint(cfg.get("set", 0))

        self._set_bc = Broadcaster(1)

    async def setup(self):
        "retrieve state"
        await super().setup()
        await AC_use(self, self._set_bc)
        if self.state_path is not None:
            sr = self.root.sub_at(self.state_path)
            await sr.rdy_()
            try:
                st = await sr.r()
            except KeyError:
                pass
            else:
                setpoint = st.pop("setpoint", None)
                if setpoint is not None:
                    self.pid.setpoint(setpoint)
                self.pid.set_state(**st)
            self.state_rtc = sr

    doc_sw = dict(_d="update state", **_state_d)

    def cmd_sw(self, t: int | None, e: float | None, i: float | None, **_kw):
        "Update the PID state."
        self.pid.set_state(t, e, i)

    doc_w = dict(_d="step", _0="float:current value", _r="float:new output")

    async def cmd_w(self, val: float, t: int | None = None) -> float:
        """
        Run a PID step.
        """
        self.val_in = val
        self.split = s = self.pid.integrate(val, t=t)
        if self._locked:
            i_new = s[1]
            lock_up = self._lock_up
            i_limit = self._lock_i
            if (
                lock_up is None
                or (lock_up and i_new > i_limit)
                or (not lock_up and i_new < i_limit)
            ):
                self.pid.i = i_limit
                self.pid.state.i = i_limit
                self.split = s = (s[0], i_limit, s[2])
        if (sr := self.state_rtc) is None and self.state_path is not None:
            self.state_rtc = sr = self.root.sub_at(self.state_path)
            await sr.rdy_()
        if sr is not None:
            await sr.cmd(Path.build(("w",)), self.pid.state, fs=False)
        return self.pid.sum(s)

    doc_sp = dict(
        _d="setpoint",
        _a=[
            dict(_d="set", _0="float:new setpoint"),
            dict(_d="read", _r="float:current setpoint"),
        ],
    )

    async def cmd_sp(self, sp: float | None = None):
        "Sets/Returns the current setpoint"
        if sp is None:
            return self.pid.state.setpoint
        self.pid.setpoint(sp)
        self._set_bc(sp)

    doc_s = dict(
        _d="read state",
        _r=dict(
            state=_state_d,
            i="float:last input",
            o="float:last output",
            split="list[float]:p-i-d output",
            fct=["float:factor", "float:offset"],
        ),
        **_state_d,
    )

    async def stream_sp(self, msg: Msg):
        "Sets/Returns the current setpoint"
        async with msg.stream() as ms, TaskGroup() as tg:

            @tg.start_soon
            async def _sp_evt():
                async with self._set_bc.reader(1) as spr:
                    async for sp in spr:
                        await ms.send(sp)

            async for m in ms:
                self.pid.setpoint(m[0])
                self._set_bc(m[0])

    async def cmd_s(self, **kw):
        """
        Sets/Returns the current state.
        """
        if kw:
            self.pid.set_state(**kw)
        res = dict(
            state=self.pid.state,
            i=self.val_in,
            split=self.split,
            fct=self.pid.get_offset(),
            gain=self.pid.get_gains(),
        )
        if self.split:
            res["o"] = self.pid.sum(self.split)
        return res

    doc_lock = dict(
        _d="I-term lock",
        up="bool|None:block I increase(T), decrease(F), or all change(None)",
    )

    async def stream_lock(self, msg: Msg):
        """
        Inhibits I-term updates.

        While a Lock command is active, the I part of the PID cannot
        increase / decrease further (controlled by the ``up`` parameter).

        Params:
        - up: prevents I from increasing (True), decreasing (False) or
          changing at all (None)

        Only one lock can be active at a time.
        """
        if self._locked:
            raise RuntimeError("PID lock already active")
        self._locked = True
        self._lock_up = msg.get("up", None)
        self._lock_i = self.pid.i
        try:
            async with msg.stream_in() as ms:
                async for _ in ms:
                    pass
        finally:
            self._locked = False

    async def reload(self):
        "reload me"
        await super().reload()
        self.pid.cfg_updated()
        self.state_rtc = None
        self.state_path = self.cfg.get("state", None)
