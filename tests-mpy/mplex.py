# micropython

import sys
import os

dd = sys.argv[1] if sys.argv else "/tmp/test-upy"
mode = sys.argv[2] if len(sys.argv)>2 else "once"
root=dd+"/root"
try:
    os.mkdir(dd)
    os.mkdir(root)
except OSError:
    pass


h = os.getcwd()
d = os.sep.join(sys.argv[0].split(os.sep)[:-2])  # /wherever/moat[/micro]
try:
    os.stat(d+os.sep+"micro")
except OSError:
    pass
else:
    d+=os.sep+"micro"
os.chdir(dd)

for p in os.getenv("PYTHONPATH").split(":"):
    if p == ".":
        p = h
    elif p.startswith("."):
        p = h+"/"+p
    ep = p+"/moat/micro/_embed"
    try:
        os.stat(ep)
    except OSError:
        pass
    else:
        sys.path.insert(0,ep)
        try:
            os.stat(ep+"/lib")
        except OSError:
            pass
        else:
            sys.path.insert(0,ep+"/lib")
sys.path.insert(0,".")
sys.path.insert(0,d+"/lib/micropython/extmod")

# TODO uasyncio's lazy importer doesn't yet mesh well with our micropython path hack
import uasyncio
import uasyncio.event
import uasyncio.lock
import uasyncio.taskgroup
import uasyncio.stream
sys.path.insert(0,d+"/lib/micropython-lib/uasyncio.queues/")
import uasyncio.queues

import main
main.go_moat("mode", fake_end=False, log=True)

