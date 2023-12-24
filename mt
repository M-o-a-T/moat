#!/usr/bin/python3

"""
This is a command line for MoaT that works in the main repository.
"""
# assume that sys.path[0] is the main …/moat directory

FORMAT = (
    "%(asctime)-15s %(threadName)-15s %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
)
import logging
logging.basicConfig(format=FORMAT, level=logging.WARNING)

def nbc(*a,**k):
    logging.warning(f"Logging: another basicConfig call: ignored {a} {k} ")
logging.basicConfig = nbc

try:
    import pymodbus.constants  # breaks logging setup if imported later
except ImportError:
    pass

import moat.__main__
