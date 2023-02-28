# micropython

import usys
import uos

dd= usys.argv[1] if usys.argv else "/tmp/test-upy"
try:
    uos.mkdir(dd)
except OSError:
    pass
d=uos.getcwd()
try:
    uos.stat(d+"/micro")
except OSError:
    pass
else:
    d+="/micro"
uos.chdir(dd)

usys.path.insert(0,d+"/moat/micro/_embed/")
usys.path.insert(0,dd)
usys.path.insert(0,d+"/moat/micro/_embed/lib")
usys.path.insert(0,d+"/lib/micropython/extmod")

# TODO the uasyncio lazy importer is *very* annoying
import uasyncio
import uasyncio.event
import uasyncio.lock
import uasyncio.taskgroup
import uasyncio.stream
usys.path.insert(0,d+"/lib/micropython-lib/uasyncio.queues/")
import uasyncio.queues

with open(d+"/configs/fallback_pipe.msgpack","rb") as f:
    c=f.read()
with open(dd+"/moat.cfg","wb") as f:
    f.write(c)

import main
main.go_moat("once", fake_end=False, log=True)

