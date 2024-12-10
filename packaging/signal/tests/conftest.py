import sys
import pook
import pook.api as _pa
import pook.interceptors as _pi
from pook.interceptors._httpx import HttpxInterceptor
_pi.add(HttpxInterceptor)
