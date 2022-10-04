"""
This module calculates optimal battery charge/discharge based on usage and
pricing prediction.

"""
from .battery import Battery
from .control import propose, FutureData
