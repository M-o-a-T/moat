#!/bin/sh -ex

export PYTHONPATH="$(dirname "$0")"/../..
cd $1/heating/KWB
. code/rebuild.sh
