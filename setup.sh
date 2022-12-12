#!/bin/sh

set -ex

D="$(pwd)"
cd modbus/moat/modbus/dev/_data/heating/KWB
sh code/rebuild.sh 
cd "$D"
apt install eatmydata
eatmydata apt install \
	python3-anyio \
	python3-anyio-serial \
	python3-cffi \
	python3-gitpython \
	python3-packaging \
	python3-pymodbus \
	python3-tomlkit \
	python3-trio \
	# end


git config --global fetch.recurseSubmodules true
git config --global pull.rebase false
