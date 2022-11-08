#!/bin/bash

set -e

apk --no-cache --quiet --no-progress add \
  py3-virtualenv
python3 -m virtualenv /tmp/venv
. /tmp/venv/bin/activate
pip3 install poetry
poetry publish --build
