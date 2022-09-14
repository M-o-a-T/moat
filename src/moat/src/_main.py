# command line interface

import os
import sys

import anyio
import json
import socket

from moat.util import yload

import asyncclick as click
import git
from pathlib import Path
from collections import defaultdict

import logging
logger = logging.getLogger(__name__)

class Repo(git.Repo):
	def __init__(self, *a,**k):
		super().__init__(*a,**k)
		self._subrepo_cache = {}
		self._commit_tags = defaultdict(list)
		self._commit_topo = {}

		for t in self.tags:
			self._commit_tags[t.commit].append(t)


	def subrepos(self):
		"""List subrepositories (and cache them).
		"""
		for r in self.submodules:
			try:
				yield self._subrepo_cache[r.path]
			except KeyError:
				self._subrepo_cache[r.path] = res = Repo(r.path)
				yield res

	def commits(self, ref=None):
		"""Iterate over topo sort of commits following @ref, or HEAD"""
		if ref is None:
			ref = self.head.commit
		try:
			res = self._commit_topo[ref]
		except KeyError:
			visited = set()
			res = []

			def _it(c):
				return iter(sorted(c.parents, key=lambda x:x.committed_date))

			work = [(c, _it(c))]

			while work:
				c,gen = work.pop()
				visited.add(c)
				for n in gen:
					if c not in visited:
						work.append((c, gen))
						work.append((n, _it(n)))
						break
				else:
					stack.append(c)
			self._commit_topo[ref] = res

		n = len(res)
		while n:
			n -= 1
			yield res[n]

	def tagged(self, c):
		if c not in self._commit_tags:
			return None
		tt = self._commit_tags[c]
		if len(tt) > 1:
			raise ValueError(f"multiple tags: {tt}")
		return tt[0]


@click.group(short_help="Manage MoaT itself")
@click.pass_obj
async def cli(obj):
	"""
	This collection of commands is useful for managing and building MoaT itself.
	"""
	pass

@cli.command()
@click.pass_obj
async def build(obj):
	"""
	Rebuild all modified packages.
	"""
	bad = False
	repo = Repo()
	for r in repo.subrepos():
		if r.is_dirty():
			print("DIRTY",Path(r.working_dir).name)
			bad = True
		t = r.tagged(r.head.commit)
		if t is None:
			print("UNTAGGED",Path(r.working_dir).name)
			bad = True
		else:
			print("TAG",t,Path(r.working_dir).name)
	if bad:
		return
	for r in rr:
		pass

