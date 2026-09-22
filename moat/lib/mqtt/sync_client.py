from __future__ import annotations  # noqa: D100

from anyio.from_thread import BlockingPortal, start_blocking_portal
from contextlib import ExitStack, contextmanager

from attrs import define

from ._types import (
    Buffer,
    MQTTPublishPacket,
    PropertyType,
    PropertyValue,
    QoS,
    RetainHandling,
    Will,
)
from .async_client import AsyncMQTTClient, AsyncMQTTSubscription

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ssl import SSLContext
    from types import TracebackType

    from collections.abc import Generator
    from typing import Any, Literal, Self


@define(eq=False, repr=False, slots=True)
class MQTTSubscription:  # noqa: D101
    async_subscription: AsyncMQTTSubscription
    portal: BlockingPortal

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> MQTTPublishPacket:
        try:
            return self.portal.call(self.async_subscription.__anext__)
        except StopAsyncIteration:
            raise StopIteration from None


class MQTTClient:  # noqa: D101
    _exit_stack: ExitStack
    _portal: BlockingPortal

    def __init__(
        self,
        host_or_path: str | None = None,
        port: int | None = None,
        *,
        transport: Literal["tcp", "unix"] = "tcp",
        websocket_path: str | None = None,
        ssl: bool | SSLContext = False,
        client_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
        clean_start: bool = True,
        receive_maximum: int = 65535,
        max_packet_size: int | None = None,
        will: Will | None = None,
    ) -> None:
        self._ctor_args = (host_or_path, port)
        self._ctor_kwargs: dict[str, Any] = {
            "transport": transport,
            "websocket_path": websocket_path,
            "ssl": ssl,
            "username": username,
            "password": password,
            "clean_start": clean_start,
            "receive_maximum": receive_maximum,
            "max_packet_size": max_packet_size,
            "will": will,
        }
        if client_id is not None:
            self._ctor_kwargs["client_id"] = client_id

        # Primitives (locks, events) inside the client must all belong to ONE
        # event loop; constructing the client inside the portal guarantees that
        # irrespective of how/where this object was instantiated.
        self._async_client: AsyncMQTTClient | None = None

    @property
    def async_client(self) -> AsyncMQTTClient:
        "The underlying async client; available after entering."
        if self._async_client is None:
            raise RuntimeError("MQTTClient not entered (use it as a context manager)")
        return self._async_client

    @property
    def cap_retain(self) -> bool:  # noqa: D102
        return self.async_client.cap_retain

    @property
    def cap_subscription_ids(self) -> bool:  # noqa: D102
        return self.async_client.cap_subscription_ids

    @property
    def cap_qos(self) -> QoS:  # noqa: D102
        return self.async_client.cap_qos

    def __enter__(self) -> Self:
        with ExitStack() as exit_stack:
            self._portal = exit_stack.enter_context(start_blocking_portal("asyncio"))

            def build() -> AsyncMQTTClient:
                return AsyncMQTTClient(*self._ctor_args, **self._ctor_kwargs)

            client = self._portal.call(build)
            exit_stack.callback(self._unset_client)
            exit_stack.enter_context(self._portal.wrap_async_context_manager(client))
            self._async_client = client
            self._exit_stack = exit_stack.pop_all()

        return self

    def _unset_client(self) -> None:
        self._async_client = None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return self._exit_stack.__exit__(exc_type, exc_val, exc_tb)

    def publish(  # noqa: D102
        self,
        topic: str,
        payload: Buffer | str,
        *,
        qos: QoS = QoS.AT_MOST_ONCE,
        retain: bool = False,
        properties: dict[PropertyType, PropertyValue] | None = None,
    ) -> None:
        return self._portal.call(
            lambda: self.async_client.publish(
                topic, payload, qos=qos, retain=retain, properties=properties
            )
        )

    @contextmanager
    def subscribe(  # noqa: D102
        self,
        *patterns: str,
        qos: QoS = QoS.EXACTLY_ONCE,
        no_local: bool = False,
        retain_as_published: bool = True,
        retain_handling: RetainHandling = RetainHandling.SEND_RETAINED,
    ) -> Generator[MQTTSubscription, None, None]:
        ac = self.async_client
        async_cm = ac.subscribe(
            *patterns,
            qos=qos,
            no_local=no_local,
            retain_as_published=retain_as_published,
            retain_handling=retain_handling,
        )
        with self._portal.wrap_async_context_manager(async_cm) as async_subscription:
            yield MQTTSubscription(async_subscription, self._portal)


def _copy_docstrings() -> None:
    "Copy the docstrings from the async variant to the sync façade."

    for attrname in dir(AsyncMQTTClient):
        if attrname.startswith("_"):
            continue
        value = getattr(AsyncMQTTClient, attrname)
        if not callable(value):
            continue
        sync_attr = getattr(MQTTClient, attrname, None)
        if sync_attr is not None and callable(sync_attr) and not sync_attr.__doc__:
            sync_attr.__doc__ = value.__doc__


_copy_docstrings()
