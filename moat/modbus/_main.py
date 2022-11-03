from moat.util import load_subgroup

from .__main__ import mk_client,mk_server

@load_subgroup(sub_pre="moat.modbus")
async def cli():
    """Modbus tools"""
    pass

client = mk_client(cli)
server = mk_server(cli)
