#!/usr/bin/python3
Import("env")
try:
    Import("projenv")
except Exception:
    projenv = None

def skip_fake(node):
    # to ignore file from a build process, just return None
    if node.get_dir().name in {"fakebus","tests"}:
        return None
    return node

def run_pre():
    env.AddBuildMiddleware(skip_fake, "*")

def run_post():
    pass


if projenv:
    run_post()
else:
    run_pre()
