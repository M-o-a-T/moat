# micropython

import sys
import os

root = sys.argv[1] if len(sys.argv)>1 else "/tmp/test-upy"
mode = sys.argv[2] if len(sys.argv)>2 else "once"
try:
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

# print("DIR:",root, file=sys.stderr)
os.chdir(root)

for p in os.getenv("PYTHONPATH").split(":"):
    if p == ".":
        p = h
    elif p.startswith("."):
        p = h+"/"+p
    ep = p+"/moat/micro/_embed"
    try:
        os.stat(ep)
    except OSError:
        # print ("NO",ep,file=sys.stderr)
        pass
    else:
        # print ("YS",ep,file=sys.stderr)
        sys.path.insert(0,ep)
        try:
            os.stat(ep+"/lib")
        except OSError:
            pass
        else:
            # print ("YS",ep+"/lib",file=sys.stderr)
            sys.path.insert(0,ep+"/lib")
sys.path.insert(0,"./stdlib")
sys.path.insert(0,".")
sys.path.insert(0,d+"/lib/micropython/extmod")

# TODO asyncio's lazy importer doesn't yet mesh well with our micropython path hack
import asyncio
import asyncio.event
import asyncio.lock
import asyncio.taskgroup
import asyncio.stream
sys.path.insert(0,d+"/lib/micropython-lib/asyncio.queues/")
#import asyncio.queues

import main
main.go_moat(mode, fake_end=False, log=True)

