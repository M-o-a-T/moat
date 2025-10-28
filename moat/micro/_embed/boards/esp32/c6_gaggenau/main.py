"""
This is a (temporary) standalone main for the Gaggenau controller replacement.
"""

from __future__ import annotations

import os
import sys
from time import sleep_ms, ticks_diff, ticks_ms, ticks_us

try:
    from micropython import const
except ImportError:

    def const(x):
        "Fake const"
        return x


import network
from mplex import Multiplex
from rtc import get_rtc as _get_rtc
from rtc import set_rtc as rtc_set

from machine import Pin

# Network configuration


cfg = dict(
    wlan=dict(
        SSID="***",
        PASSWORD="*** *** ***",  # noqa:S106
        STATIC_IP="10.107.0.42",
        SUBNET="255.255.255.0",
        GATEWAY="10.107.0.1",
        DNS="8.8.8.8",
    ),
    light=21,  # inverted
    triac=dict(
        input=0,
        output=20,  # inverted
    ),
    buttons=dict(
        scan=[22, 23, 3, 2],
        input=[10, 11],
        output=[12, 13],
        inv=dict(
            scan=True,
            input=False,
            output=False,
        ),
        msec=5,
        timer=1,
    ),
)

wlan = None


def wifi(cfg: dict | None = None):
    "setup wifi"
    global wlan

    if wlan is None:
        wlan = network.WLAN(network.STA_IF)
    if cfg is None:
        wlan.active(False)
        return

    wlan.active(True)

    # Configure static IP
    wlan.ifconfig((cfg["STATIC_IP"], cfg["SUBNET"], cfg["GATEWAY"], cfg["DNS"]))
    wlan.connect(cfg["SSID"], cfg["PASSWORD"])


def mwifi():
    "manually open the wifi link"
    wifi(cfg["wlan"])
    import webrepl  # noqa:PLC0415

    webrepl.start()


B_Fn = const(0)
B_Light = const(1)
B_Time = const(2)
B_Int = const(3)
B_3 = const(4)
B_2 = const(5)
B_1 = const(6)
B_0 = const(7)


def rtc(name, default):
    "read rtc state"
    res = _get_rtc(name)
    if res is None:
        res = default
    return res


class Gaggenau:
    "Controller"

    wifi_do = False
    t_wifi_last = None
    t_wifi_ok = None
    mp: Multiplex | None = None

    def __init__(self, cfg):
        self.cfg = cfg
        self.mp = Multiplex(cfg["buttons"])
        self._light = Pin(cfg["light"], Pin.OUT, value=1)
        self._fan = Pin(cfg["triac"]["output"], Pin.OUT, value=1)

    def start(self):
        "Setup"
        self.mp.start()
        self._fan(not rtc("fan", 0))
        self._light(not rtc("light", 0))
        self.t_wifi_last = ticks_ms()

        if rtc("wifi", False):
            rtc_set("wifi", False)
            self.wifi_do = True
            wifi(True)

        if self.fan:
            self.mp[B_3] = True
        if self.light:
            self.mp[B_Light] = True

    def stop(self):
        "Teardown"
        self.mp.stop()
        self._fan(1)
        self._light(1)

    @property
    def light(self):
        "Light state"
        return not self._light()

    @light.setter
    def light(self, val):
        "Light state"
        self._light(not val)
        rtc_set("light", val)

    @property
    def fan(self):
        "Fan state"
        return not self._fan()

    @fan.setter
    def fan(self, val):
        "Fan state"
        self._fan(not val)
        rtc_set("fan", val)

    def run(self):
        "Run loop"
        try:
            print("* MoaT Herd * Task starts *")
            self.start()
            while True:
                try:
                    self.step()
                except Exception as exc:
                    sys.print_exception(exc)
                    sleep_ms(1000)
                else:
                    sleep_ms(100)
        except BaseException:
            self.stop()
            raise

    def time_step(self):
        "time a step"
        a = ticks_us()
        self.step()
        b = ticks_us()
        return ticks_diff(b, a)

    def step(self):
        "Run one pass"
        tm = ticks_ms()
        for btn, val in self.mp.changes():
            print(btn, val)
            if not val:
                return
            if btn == B_Light:
                self.light = not self.light
                self.mp[B_Light] = self.light
            elif btn == B_3:
                self.fan = 1
                self.mp[B_1] = 0
                self.mp[B_2] = 0
                self.mp[B_3] = 1
            elif btn == B_0:
                self.fan = 0
                self.mp[B_1] = 0
                self.mp[B_2] = 0
                self.mp[B_3] = 0
            elif btn == B_Fn:
                if rtc("wifi", False) or self.wifi_do or (wlan is not None and wlan.isconnected()):
                    wifi(None)
                    self.wifi_do = False
                    self.mp[B_Fn] = False
                    rtc_set("wifi", False)
                    self.t_wifi_last = None
                else:
                    wifi(self.cfg["wlan"])
                    self.mp[B_Fn] = True
                    self.t_wifi_last = ticks_ms()
                    self.wifi_do = True

        # Now handle wifi.
        if self.t_wifi_last is not None and ticks_diff(tm, self.t_wifi_last) > 750:
            self.t_wifi_last = tm
            if self.wifi_do:
                if wlan.isconnected():
                    self.wifi_do = False
                    self.t_wifi_ok = ticks_ms()
                    self.mp[B_Fn] = True

                    try:
                        os.stat("webrepl_cfg.py")
                    except OSError:
                        pass
                    else:
                        import webrepl  # noqa:PLC0415

                        webrepl.start()
                else:
                    self.mp[B_Fn] = not self.mp.get_out(B_Fn)

            elif wlan is None or not wlan.isconnected():
                self.mp[B_Fn] = False

            else:
                self.mp[B_Fn] = True
                if self.t_wifi_ok is not None and ticks_diff(tm, self.t_wifi_last) > 30000:
                    self.t_wifi_ok = None
                    rtc_set("wifi", True)


if rtc("run", True):
    ga = Gaggenau(cfg)
    ga.run()
