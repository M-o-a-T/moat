# micropython

import sys
import os

mode = sys.argv[1] if len(sys.argv)>1 else "once"


h = os.getcwd()
d = os.sep.join(sys.argv[0].split(os.sep)[:-2])  # /wherever/moat[/micro]
try:
    os.stat(d+os.sep+"micro")
except OSError:
    pass
else:
    d+=os.sep+"micro"

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

import main
main.go(mode, fake_end=False)

