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
This code implements logging to RRD.

"""

import six

from moat.check import register_condition,unregister_condition
from moat.module import Module
from moat.statement import Statement, main_words
from moat.times import now
from moat.twist import fix_exception
from moat.base import Name
from moat.collect import Collection,Collected

import os
import rrdtool

class RRDs(Collection):
	name = "rrd"
RRDs = RRDs()
RRDs.does("del")

class RRD(Collected):
	storage = RRDs
	def __init__(self,path,dataset,name):
		self.path = path
		self.upath = path.encode("utf-8")
		self.dataset = dataset
		self.udataset = dataset.encode("utf-8")
		super(RRD,self).__init__(*name)
		 
	def list(self):
		yield super(RRD,self)
		yield ("file",self.path)
		yield ("dataset",self.dataset)
		try:
			for k,v in rrdtool.info(self.upath)["ds"][self.udataset].items():
				yield (k,v)
		except KeyError:
			s="ds[%s]." % (self.udataset)
			d=rrdtool.info(self.upath)
			# mainly for testing
			for k in sorted(x for x in d.keys() if x.startswith(s)):
				yield (k[len(s):],d[k])

	def info(self):
		return "%s %s" % (self.path,self.dataset)

class RRDHandler(Statement):
	name="rrd"
	doc="Creates an RRD object"
	long_doc=u"""\
rrd path dataset NAME…
	Create a named RRD object.
	: NAME is a mnemonic name for this RRD.
	PATH is the file name. You probably need to quote it.
	DATASET is the dataset name in the RRD.
"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if len(event) < 3:
			raise SyntaxError(u'Usage: rrd "/path/to/the.rrd" ‹varname› ‹name…›')
		fn = event[0]
		assert os.path.exists(fn), "the RRD file does not exist: ‹%s›" % (fn,)
		RRD(path=fn, dataset=event[1], name=Name(*event[2:]))

class VarRRDHandler(Statement):
	name="var rrd"
	doc="assign a variable to some RRD state"
	long_doc=u"""\
var rrd variable item NAME
	: Assigns the named RRD dataset variable to a variable.
	"rrdtool info" prints this in ds[‹variable›] lines:
	ds[‹dataset›].‹item› = ‹value-of-item›

"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if len(event) < 3:
			raise SyntaxError(u'Usage: var rrd ‹variable› ‹item› ‹name…›')
		s = RRDs[Name(*event[2:])]
		try:
			setattr(self.parent.ctx,event[0],rrdtool.info(s.upath)["ds"][s.dataset][event[1]])
		except KeyError:
			setattr(self.parent.ctx,event[0],rrdtool.info(s.upath)["ds[%s].%s" % (s.dataset,event[1])])

class RRDset(Statement):
	name="set rrd"
	doc="write a variable to a RRD file"
	long_doc=u"""\
set rrd value ‹name…›
	: Assigns the named RRD dataset variable to a variable.
	"rrdtool info" prints this in ds[‹variable›] lines:
	ds[‹dataset›].‹item› = ‹value-of-item›

"""
	def run(self,ctx,**k):
		event = self.params(ctx)
		if len(event) < 2:
			raise SyntaxError(u'Usage: set rrd ‹value› ‹name…›')
		s = RRDs[Name(*event[1:])]
		# Using "N:" may run into a RRD bug
		# if we're really close to the next minute
		try:
			rrdtool.update(s.upath, str("-t"),s.udataset, str(now().strftime("%s")+":"+six.text_type(event[0])).encode("utf-8"))
		except Exception as e:
			fix_exception(e)
			if "minimum one second step" in str(e):
				pass
			else:
				raise

class RRDModule(Module):
	"""\
		This module provides tools for working with RRDs.
		"""

	info = "Words for RRD access"

	def load(self):
		main_words.register_statement(RRDHandler)
		main_words.register_statement(RRDset)
		main_words.register_statement(VarRRDHandler)
		register_condition(RRDs.exists)
	
	def unload(self):
		main_words.unregister_statement(RRDHandler)
		main_words.unregister_statement(RRDset)
		main_words.unregister_statement(VarRRDHandler)
		unregister_condition(RRDs.exists)
	
init = RRDModule
