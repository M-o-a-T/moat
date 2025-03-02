#!/bin/sh

set -ex

# rebuild generated tables

D="$(pwd)"
cd modbus/moat/modbus/dev/_data/heating/KWB
sh code/rebuild.sh 
cd "$D"

# get the dependencies' latest versions 

if test -d .venv ; then
	. .venv/bin/activate
	pip install -r requirements.txt
elif test -x /usr/bin/apt; then
    sudo apt update
    test -x /usr/bin/eatmydata || sudo apt install eatmydata
    sudo eatmydata apt install \
	    python3-anyio \
	    python3-anyio-serial \
	    python3-cffi \
	    python3-git \
	    python3-packaging \
	    python3-pymodbus \
	    python3-tomlkit \
	    python3-trio \
	    # end
else  # patches to adapt to other distributions welcome
	echo "I don't know how to install Python requirements. Please do so manually." >&2
	exit 1
fi

