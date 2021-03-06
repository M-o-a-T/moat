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

"""Simple server that listens on port 6000 and echos back every input to the client.

Connect to it with:
telnet localhost 6000

Terminate the connection by terminating telnet (typically Ctrl-] and then 'quit').
"""
import gevent
from gevent.server import StreamServer

def rrdc_me(socket, address):
	print(('New connection from %s:%s' % address))
	fileobj = socket.makefile()

	line = fileobj.readline()
	fileobj.write("0 Yes\n")
	fileobj.flush()

	line = fileobj.readline()
	fileobj.write("2 Nonsense follows\n")
	fileobj.write("Nonsense\n")
	fileobj.write("More Nonsense\n")
	fileobj.flush()

	while True:
		line = fileobj.readline()
		if line is None or line == "":
			break
		fileobj.write("-123 No\n")
		fileobj.flush()

if __name__ == '__main__':
	# to make the server use SSL, pass certfile and keyfile arguments to the constructor
	s1 = StreamServer(('localhost', 52442), rrdc_me)
	s1.start()

	gevent.sleep(30)
	s1.stop()
