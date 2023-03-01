# micropython

import usys
import uos

dd = usys.argv[1] if usys.argv else "/tmp/test-upy"
mode = usys.argv[2] if len(usys.argv)>2 else "once"
root=dd+"/root"
try:
    uos.mkdir(dd)
    uos.mkdir(root)
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
usys.path.insert(0,".")
usys.path.insert(0,d+"/moat/micro/_embed/lib")
usys.path.insert(0,d+"/lib/micropython/extmod")

# TODO uasyncio's lazy importer doesn't yet mesh well with our micropython path hack
import uasyncio
import uasyncio.event
import uasyncio.lock
import uasyncio.taskgroup
import uasyncio.stream
usys.path.insert(0,d+"/lib/micropython-lib/uasyncio.queues/")
import uasyncio.queues

import main
main.go_moat("mode", fake_end=False, log=True)

