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

"""\
This code reads a config file.

	include NAME
		- read that file

"""

from moat.statement import Statement, main_words
from moat.module import Module
from moat.check import Check,register_condition,unregister_condition
from moat.parser import parse
import os

class Include(Statement):
	name="include"
	doc="load a configuration file"
	long_doc = """\
include 'NAME'
	reads and processes the named configuration file.
	The name probably needs to be quoted.
"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if len(event) != 1:
			raise SyntaxError("Usage: include 'filename'")
		parse(event[0],ctx=ctx)

class FileModule(Module):
	"""\
		This module implements a few file-related functions.
		"""

	info = "Basic (include) file handling"

	def load(self):
		main_words.register_statement(Include)
	
	def unload(self):
		main_words.unregister_statement(Include)
	
init = FileModule
