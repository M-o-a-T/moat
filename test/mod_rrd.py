#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaT, the Master of all Things.
##
##  MoaT is Copyright © 2007-2016 by Matthias Urlichs <matthias@urlichs.de>,
##  it is licensed under the GPLv3. See the file `README.rst` for details,
##  including optimistic statements by the author.
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
##  This header is auto-generated and may self-destruct at any time,
##  courtesy of "make update". The original is in ‘scripts/_boilerplate.py’.
##  Thus, do not remove the next line, or insert any blank lines above.
##BP

import six
if six.PY3:
	import sys; sys.exit(121)

from moat import patch;patch()
from moat.reactor import ShutdownHandler
from moat.module import load_module
from moat.statement import main_words
from test import run

input = """\
log DEBUG STARTING_UP
block:
	if exists rrd t tt ttt:
		log ERROR No1
	else:
		log TRACE Yes
rrd "/tmp/rrdtest.rrd" test t tt ttt
block:
	if exists rrd t tt ttt:
		log TRACE Yes
	else:
		log ERROR No2
list rrd
list rrd t tt ttt
wait: for 1.1
set rrd 10 t tt ttt
wait: for 1.1
set rrd 11 t tt ttt
wait: for 1.1
set rrd 12 t tt ttt
list rrd t tt ttt
block:
	var rrd x last_ds t tt ttt
	trigger last $x
del rrd t tt ttt
block:
	if exists rrd t tt ttt:
		log ERROR No3
	else:
		log TRACE Yes

"""

main_words.register_statement(ShutdownHandler)
load_module("trigger")
load_module("ifelse")
load_module("data")
load_module("rrd")
load_module("logging")
load_module("block")
load_module("wait")

run("rrd",input)

