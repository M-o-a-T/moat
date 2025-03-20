Installing the moat.micro client
================================

The *moat.micro* client is a Python program, running on MicroPython.

Most controllers have quite limited RAM. The first step is therefore to
build a patched version of MicroPython that includes the *moat.micro* core.

The script ``scripts/install`` does this for you. It needs a configuration
file. The ``deploy`` subdirectory contains some examples.



