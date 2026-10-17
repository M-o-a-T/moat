#!/bin/bash

# SPDX-License-Identifier: GPL-3.0-or-later

set -eux -o pipefail -o errexit

test -v VENV || export VENV=N
test -v UPY || export UPY=Y
test -v ESP || export ESP=Y
test -v IDF || export IDF=v5.5.4

WT="$(pwd)"
M=$(git worktree list | head -1 | sed -e 's/ .*//')
test -v EXT || EXT=moat_ext

cd "$M/.."
D="$(pwd)"
cd "$M"
M="$(pwd)"
cd "$D"

if [ "$M" != "$WT" ] ; then
    if ! test -d "$EXT" ; then
        echo "Extensions dir '$D/$EXT' not found; run 'setup.sh' in the main checkout first." >&2
        exit 1
    fi

    cd "$WT"
    test -d .venv || cp -a --reflink=auto "$M/.venv" .venv
    rm -rf ext; ln -sf "$D/$EXT" ext

    exit 0
fi

cd "$M"
if ! test -d ext ; then
    rm -rf ext
    ln -sf "$D/$EXT" ext
fi

if ! test -s /etc/apt/sources.list.d/smurf.list ; then
    wget -O - -q https://debian.m-u.xyz/info/GET | sudo bash
fi
sudo apt install -U -y eatmydata

if [ "$VENV" = "n"]
sudo eatmydata apt install -y \
    flashmq victoria-metrics knxd \
    git sourcemgr build-essential pkg-config cmake ty ruff \
    libffi-dev

if [ "$VENV" = "n" ]
    sudo eatmydata apt install -y \
        python3-anyio python3-asyncclick python3-asyncscope python3-simpleeval \
        python3-attr python3-ruamel.yaml python3-tomlkit python3-pytest \
        python3-jinja2 python3-httpx python3-transitions python3-jmespath \
        python3-alembic python3-jsonschema python3-serial python3-wsproto \
        python3-range-set python3-asyncwebsockets python3-pyfuse3 \
        python3-stamina python3-asyncactor python3-aiocaldav
else
    sudo eatmydata apt install -y python3-venv
fi

if [ "$ESP" = Y ] ; then
    if ! test -d esp-idf ; then
        git clone --recurse-submodules https://github.com/espressif/esp-idf.git esp-idf
    fi
    cd esp-idf

    if [ $(git rev-parse HEAD) != $(git rev-parse "$IDF"'^{commit}') ] ; then
        git switch --detach "$IDF"
        git submodule update --init --recursive
    fi
    cd "$D"
fi

cd "$M"
if [ "$VENV" = "Y" ] ; then
    export PATH=.venv/bin:$(PATH)
    if test -d .venv ; then
        uv pip install -U
    else
        python3 -mvenv .venv
        pip install uv
        uv pip install -e .
        uv pip install -e .[dev]
        uv pip install -e .[doc]
        uv pip install ty pre-commit
    fi

elif test -d .venv ; then
    rm -rf .venv
fi

if ! test -e moat-ext/.OK ; then
    mkdir -p "$D/moat-ext"
    rm -f ext
    ln -s "$D/moat-ext" ext
    ./mt src submod get
    touch $D/moat-ext/.OK
fi

make -C ext/micropython/mpy-cross
env PYTHONPATH=$M \
    make -C ext/micropython/ports/unix \
        VARIANT_DIR=$M/moat/micro/_embed/boards/unix/test \
        BUILD=$M/build/mpy-unix \
        STRIP= DEBUG=1
