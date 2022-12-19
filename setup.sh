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


git config --global fetch.recurseSubmodules on-demand
git config --global push.recurseSubmodules on-demand
git config --global pull.rebase false

T=$(mktemp)
trap 'rm -f $T' EXIT INT

cat <<'__END' >$T
#!/bin/sh

if git config remote.origin.url | fgrep -qs 'git://git.smurf.noris.de/moat' ; then
	git config remote.origin.url $(git config remote.origin.url | sed -e 's#git://git.smurf.noris.de/#git@git.smurf.noris.de:#')
fi

__END

git submodule foreach --recursive /bin/sh $T
