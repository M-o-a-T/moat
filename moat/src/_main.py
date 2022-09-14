# command line interface

import io
import os
import sys

import anyio
import json
import socket

from moat.util import yload, yprint, to_attrdict

import asyncclick as click
import git
import toml
import requirements
import subprocess
from pathlib import Path
from collections import defaultdict
from packaging.requirements import Requirement
from configparser import RawConfigParser

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

			work = [(ref, _it(ref))]

			while work:
				c,gen = work.pop()
				visited.add(c)
				for n in gen:
					if n not in visited:
						work.append((c, gen))
						work.append((n, _it(n)))
						break
				else:
					res.append(c)
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

def fix_deps(deps, tags):
	work = False
	for i,dep in enumerate(deps):
		r = Requirement(dep)
		if r.name.startswith("moat-"):
			n = r.name[5:]
			deps[i] = f"{r.name}~={deps[n]}"
			work = True
	return work


def run_tests(repo):
	try:
		subprocess.run(["python3","-mtox"], cwd=repo.working_dir)
	except subprocess.CalledProcessError:
		return False
	else:
		return True

class Replace:
	def __init__(self, **kw):
		self.changes = kw
	def __call__(self, s):
		if isinstance(s,str):
			for k,v in self.changes.items():
				s = s.replace(k,v)
		return s

def default_dict(*d, cls=dict, repl=lambda x:x) -> dict:
	"""
	Returns a dict with all keys+values of all dict arguments.
	The first found value wins.

	This operation is recursive and non-destructive.

	Args:
	cls (type): a class to instantiate the result with. Default: dict.
		Often used: :class:`attrdict`.
	"""
	res = cls()
	keys = defaultdict(list)
	if not len(d):
		return res

	for kv in d:
		if kv is None:
			continue
		for k, v in kv.items():
			keys[k].append(v)

	for k, v in keys.items():
		if isinstance(v[0], dict):
			res[k] = default_dict(*v, cls=cls, repl=repl)
		elif isinstance(v[0], (list,tuple)):
			res[k] = x = []
			for xx in v:
				for yy in xx:
					yy = repl(yy)
					if yy not in x:
						x.append(yy)
		else:
			res[k] = repl(v[0])

	return res


def apply_templates(repo):
	"""
	Apply templates to this repo.
	"""
	if repo.head.is_detached:
		print(f"{repo.working_dir}: detached. Skipping.")
		return
	if repo.head.ref.name != "main":
		print(f"{repo.working_dir}: on branch [repo.head.ref.name]. Skipping.")
		return
	elif repo.is_dirty(index=True, working_tree=True, untracked_files=False, submodules=False):
		print(f"{repo.working_dir}: Dirty. Skipping.")
		return

	repl = Replace(
		SUBNAME=Path(repo.working_dir).name,
	)
	pt = (Path(__file__).parent.parent.parent/"template").joinpath
	pr = Path(repo.working_dir).joinpath
	with pt("pyproject.forced.yaml").open("r") as f:
		t1 = yload(f)
	with pt("pyproject.default.yaml").open("r") as f:
		t2 = yload(f)
	try:
		with pr("pyproject.toml").open("r") as f:
			proj = toml.decoder.load(f)
			try:
				tx = proj["tool"]["tox"]["legacy_tox_ini"]
			except KeyError:
				pass
			else:
				txp = RawConfigParser()
				txp.read_string(tx)
				proj["tool"]["tox"] = td = {}
				for k,v in txp.items():
					td[k] = ttd = dict()
					for kk,vv in v.items():
						if isinstance(vv,str) and vv[0] == "\n":
							vv = [ x.strip() for x in vv.strip().split("\n") ]
						ttd[kk] = vv

	except FileNotFoundError:
		proj = {}
	p = default_dict(t1,proj,t2, repl=repl)
	if p != proj:
		try:
			tx = p["tool"]["tox"]
		except KeyError:
			pass
		else:
			txi = io.StringIO()
			txp = RawConfigParser()
			for k,v in tx.items():
				if k != "DEFAULT":
					txp.add_section(k)
				for kk,vv in v.items():
					if isinstance(vv,(tuple,list)):
						vv = "\n   "+"\n   ".join(str(x) for x in vv)
					txp.set(k,kk,vv)
			txp.write(txi)
			p["tool"]["tox"] = dict(legacy_tox_ini=txi.getvalue())

		with (Path(repo.working_dir)/"pyproject.toml").open("w") as f:
			toml.encoder.dump(p,f)
		repo.index.add(Path(repo.working_dir)/"pyproject.toml")
	
	mkt = repl(pt("Makefile").read_text())
	try:
		mk = pr("Makefile").read_text()
	except FileNotFoundError:
		mk = ""
	if mkt != mk:
		pr("Makefile").write_text(mk)
		repo.index.add(pr("Makefile"))
	
	try:
		with pr(".gitignore").open("r") as f:
			ign = f.readlines()
	except FileNotFoundError:
		ign = []
	o=len(ign)
	with pt("gitignore").open("r") as f:
		for li in f:
			if li not in ign:
				ign.append(li)
	if len(ign) != o:
		with pr(".gitignore").open("w") as f:
			for li in ign:
				f.write(li)
		repo.index.add(pr(".gitignore"))
	

	if repo.is_dirty(index=True, working_tree=False, untracked_files=False, submodules=False):
		repo.index.commit("Update from MoaT template")




@cli.command()
@click.pass_obj
async def setup(obj):
	"""
	Set up projects using templates.
	"""
	repo = Repo()
	for r in repo.subrepos():
		apply_templates(r)


@cli.command()
@click.option("-T","--no-test",is_flag=True,help="Skip testing")
@click.pass_obj
async def build(obj, no_test):
	"""
	Rebuild all modified packages.
	"""
	bad = False
	repo = Repo()
	tags = {}
	for r in repo.subrepos():
		if not no_test and not run_tests(r):
			print("FAIL",t,Path(r.working_dir).name)
			return  # abort immediately

		if r.is_dirty():
			print("DIRTY",Path(r.working_dir).name)
			if Path(r.working_dir).name != "src":
				bad = True
			continue
		t = r.tagged(r.head.commit)
		if t is None:
			for c in r.commits():
				t = r.tagged(c)
				if t is not None:
					break
			print("UNTAGGED",t,Path(r.working_dir).name)
			xt,t = t.name.rsplit(".",1)
			t = f"{xt}.{str(int(t)+1)}"
			# t = r.create_tag(t)
			# do not create the tag yet
		else:
			print("TAG",t,Path(r.working_dir).name)
		tags[r.working_dir] = t
	if bad:
		print("No work done. Fix and try again.")
		return

	dirty = set()

	check = True
	while check:
		check = False

		# Next: fix versioned dependencies
		for r in repo.subrepos():
			p = Path(r.working_dir) / "pyproject.toml"
			if not p.is_file():
				# bad=True
				print("Skip:",r.working_dir)
				continue
			with p.open("r") as f:
				pr = toml.decoder.load(f)

			print("***",r.working_dir)
			yprint(to_attrdict(pr))

			work = False
			try:
				deps = pr["project"]["dependencies"]
			except KeyError:
				pass
			else:
				work = fix_deps(deps, tags) | work
			try:
				deps = pr["project"]["optional_dependencies"]
			except KeyError:
				pass
			else:
				for v in deps.values():
					work = fix_deps(v, tags) | work
			if work:
				with p.open("w") as f:
					toml.encoder.dump(pr,f)
				r.index.add(p)
				dirty.add(r)
				t = tags[r.working_dir]
				if not isinstance(t, str):
					xt,t = t.name.rsplit(".",1)
					t = f"{xt}.{str(int(t)+1)}"
					tags[r.working_dir] = t
				check = True

	if bad:
		print("Partial work done. Fix and try again.")
		return

	for r in dirty:
		r.index.commit("Update MoaT requirements")
	for r in repo.subrepos():
		t = tags[r.working_dir]
		if isinstance(t, str):
			r.create_tag(t)

