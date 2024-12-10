#!/bin/bash

# reduced-scope libc
set -exu
cd picolibc
test -d build-arm-none-eabi || ./make-target arm-none-eabi
cd build-arm-none-eabi
meson configure . \
    -Dincludedir=arm/include -Dlibdir=arm/lib -Dposix-io=false -Dthread-local-storage=false \
    -Dtinystdio=true -Dnewlib-io-float=false -Dio-float-exact=false -Dnewlib-multithread=false \
    -Dnewlib-io-long-long=false -Dnewlib-global-errno=true -Datomic-ungetc=false -Dc_args= \
    -Db_ndebug=true -Dmultilib=false -Dnewlib-initfini=false -Dnewlib-initfini-array=false \
    -Dnewlib-initfini-arrayy=false -Dnewlib-elix-level=0 -Dbackend=ninja \
    -Dprefix=/home/smurf/src/moat-bus/lib -Dspecsdir=/home/smurf/src/moat-bus/lib/arm

# build
ninja

# install locally. The envvar prevents Meson from trying to obtain root privileges.
PKEXEC_UID=99999 meson install

# Build. The first pass will fail because app images depend on the
# corresponding boot loaders.
cd ../..
platformio run || \
platformio run

set +e
echo "Build done. Now flash boot loaders."
exit 0
