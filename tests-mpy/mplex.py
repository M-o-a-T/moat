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

sys.path.insert(0,"./stdlib")
sys.path.insert(0,".")

import main
main.go(mode, fake_end=False)

