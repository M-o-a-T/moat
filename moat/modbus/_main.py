"""
Basic "moat modbus" tool: network client and server, serial client
"""

from moat.util import load_subgroup

from .__main__ import mk_client, mk_serial_client, mk_server


@load_subgroup(sub_pre="moat.modbus")
async def cli():
    """Modbus tools"""
    pass


serialclient = mk_serial_client(cli)

client = mk_client(cli)
server = mk_server(cli)
