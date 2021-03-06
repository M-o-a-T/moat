#!/bin/sh

##
##  Copyright © 2007-2012, Matthias Urlichs <matthias@urlichs.de>
##
##  This program is free software: you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation, either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License (included; see the file LICENSE)
##  for more details.
##

set -e 

if test -d ../audio ; then cd ../audio
elif test -d fs20/audio ; then cd fs20/audio
elif test -d ../fs20/audio ; then cd ../fs20/audio
else echo "No audio subdir"; exit 1; fi

if make ; then

	./writer rate 32000 em fs20 exec cat < ../../test/expect/fs20rw | ./reader rate 32000 em fs20 exec cat > ../../test/real/fs20rw

else
	echo "### skipping audio codec test"
	cat ../../test/expect/fs20rw >../../test/real/fs20rw
fi
