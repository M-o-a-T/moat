#!/usr/bin/python3

"""
This is a command line for MoaT that works in the main repository.
"""
# assume that sys.path[0] is the main …/moat directory

import os
if os.path.exists("configs/mt.cfg"):
	os.environ["MOAT_CFG"]="configs/mt.cfg"

import moat.__main__
