import asyncclick as click
import random
from moatbus.backend.mqtt import MqttBusHandler
from moat.util import gen_ident, al_lower


@click.group(short_help="Display MoatBUS messages", invoke_without_command=True)
@click.option(
    "-i",
    "--ident",
    help="Identifier for this process. Must be unique. Default is random.",
)
@click.pass_context
async def cli(ctx, ident):
    """
    Log MoaTbus messages from MQTT.
    """
    obj = ctx.obj
    cfg = obj.cfg
    if ident is None:
        ident = gen_ident(9, alphabet=al_lower)

    if ctx.invoked_subcommand is not None:
        return
    async with MqttBusHandler(id=ident, uri=cfg.server.mqtt["uri"], topic=cfg.moatbus.topic) as M:
        async for msg in M:
            print(msg)
