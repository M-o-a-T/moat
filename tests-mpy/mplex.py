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


h = uos.getcwd()
d = uos.sep.join(usys.argv[0].split(uos.sep)[:-2])  # /wherever/moat[/micro]
try:
    uos.stat(d+uos.sep+"micro")
except OSError:
    pass
else:
    d+=uos.sep+"micro"
uos.chdir(dd)

for p in uos.getenv("PYTHONPATH").split(":"):
    if p == ".":
        p = h
    elif p.startswith("."):
        p = h+"/"+p
    ep = p+"/moat/micro/_embed"
    try:
        uos.stat(ep)
    except OSError:
        print("NO",ep,file=usys.stderr)
        pass
    else:
        usys.path.insert(0,ep)
        try:
            uos.stat(ep+"/lib")
        except OSError:
            pass
        else:
            usys.path.insert(0,ep+"/lib")
usys.path.insert(0,".")
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

