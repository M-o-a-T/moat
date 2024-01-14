#!/usr/bin/python3

"""
This is a command line for MoaT that works in the main repository.
"""
# assume that sys.path[0] is the main …/moat directory

import logging
def nbc(*a,**k):
    logging.debug(f"Logging: another basicConfig call: ignored {a} {k} ")
logging.basicConfig = nbc

import moat.__main__
