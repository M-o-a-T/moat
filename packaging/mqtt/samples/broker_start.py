import logging
import anyio
import os
from moat.mqtt.broker import create_broker

logger = logging.getLogger(__name__)

config = {
    "listeners": {
        "default": {"type": "tcp", "bind": "0.0.0.0:1883"},
        "ws-mqtt": {"bind": "127.0.0.1:8080", "type": "ws", "max_connections": 10},
    },
    "sys_interval": 10,
    "auth": {
        "allow-anonymous": True,
        "password-file": os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "passwd"
        ),
        "plugins": ["auth_file", "auth_anonymous"],
    },
    "topic-check": {"enabled": False},
}


async def test_coro():
    async with create_broker(config=config) as broker:  # noqa: F841, pylint: disable=W0612
        while True:
            await anyio.sleep(99999)
    # await anyio.sleep(5)
    # await broker.shutdown()


if __name__ == "__main__":
    formatter = "[%(asctime)s] :: %(levelname)s :: %(name)s :: %(message)s"
    # formatter = "%(asctime)s :: %(levelname)s :: %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=formatter)
    anyio.run(test_coro, backend="trio")
