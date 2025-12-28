# MQTT Library

% start synopsis
% start main

A sans-io_ implementation of the MQTT_ v5 protocol.

Contents:

* State machines appropriate for implementing MQTT_ clients and brokers
* Asynchronous client and broker implementations
* Synchronous client implementation, implemented by using an asyncio_ event loop thread
  behind the scenes

While the provided client I/O implementations are intended for production use, the
broker implementation should only be used in very lightweight scenarios where high
performance or a broad feature set are not required.

.. _asyncio: https://docs.python.org/3/library/asyncio.html
.. _MQTT: https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html
.. _sans-io: https://sans-io.readthedocs.io/

% end synopsis

The state machine implementation tries to adhere to the MQTT v5 protocol as tightly as
possible, and this project has certain automatic safeguards to ensure correctness:

* Ruff_ linting
* Passes Mypy_ in strict mode
* Documentation built with "fail-on-warning" enabled

.. _Ruff: https://docs.astral.sh/ruff/
.. _Mypy: https://mypy-lang.org/

% end main

You can find the documentation `here <https://m-o-a-t.org/moat.lib.mqtt/>`_.
