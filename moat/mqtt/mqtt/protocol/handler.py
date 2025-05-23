# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations
import itertools
import logging

import anyio
from moat.util import create_queue

from moat.mqtt.errors import InvalidStateError, MoatMQTTException, MQTTException, NoDataException
from moat.mqtt.session import (
    INCOMING,
    OUTGOING,
    IncomingApplicationMessage,
    OutgoingApplicationMessage,
    Session,
)
from moat.mqtt.utils import CancelledError, Future
from moat.mqtt.mqtt import packet_class
from moat.mqtt.mqtt.constants import QOS_0, QOS_1, QOS_2
from moat.mqtt.mqtt.packet import (
    CONNACK,
    DISCONNECT,
    PINGREQ,
    PINGRESP,
    PUBACK,
    PUBCOMP,
    PUBLISH,
    PUBREC,
    PUBREL,
    RESERVED_0,
    RESERVED_15,
    SUBACK,
    SUBSCRIBE,
    UNSUBACK,
    UNSUBSCRIBE,
    MQTTFixedHeader,
)
from moat.mqtt.mqtt.puback import PubackPacket
from moat.mqtt.mqtt.pubcomp import PubcompPacket
from moat.mqtt.mqtt.pubrec import PubrecPacket
from moat.mqtt.mqtt.pubrel import PubrelPacket
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.mqtt.mqtt.unsubscribe import UnsubscribePacket
    from moat.mqtt.mqtt.unsuback import UnsubackPacket
    from moat.mqtt.mqtt.subscribe import SubscribePacket
    from moat.mqtt.mqtt.suback import SubackPacket
    from moat.mqtt.mqtt.publish import PublishPacket
    from moat.mqtt.mqtt.pingresp import PingRespPacket
    from moat.mqtt.mqtt.pingreq import PingReqPacket
    from moat.mqtt.mqtt.disconnect import DisconnectPacket
    from moat.mqtt.mqtt.connect import ConnectPacket
    from moat.mqtt.mqtt.connack import ConnackPacket
    from moat.mqtt.plugins.manager import PluginManager
    from moat.mqtt.adapters import StreamAdapter

try:
    ClosedResourceError = anyio.exceptions.ClosedResourceError
    BrokenResourceError = anyio.exceptions.BrokenResourceError
    EndOfStream = anyio.exceptions.EndOfStream
except AttributeError:
    ClosedResourceError = anyio.ClosedResourceError
    BrokenResourceError = anyio.BrokenResourceError
    EndOfStream = anyio.EndOfStream

EVENT_MQTT_PACKET_SENT = "mqtt_packet_sent"
EVENT_MQTT_PACKET_RECEIVED = "mqtt_packet_received"

PACKET_TYPES = {
    CONNACK: ("connack", False),
    SUBSCRIBE: ("subscribe", True),
    UNSUBSCRIBE: ("unsubscribe", True),
    SUBACK: ("suback", False),
    UNSUBACK: ("unsuback", False),
    PUBACK: ("puback", False),
    PUBREC: ("pubrec", False),
    PUBREL: ("pubrel", False),
    PUBCOMP: ("pubcomp", False),
    PINGREQ: ("pingreq", False),
    PINGRESP: ("pingresp", False),
    PUBLISH: ("publish", True),
    DISCONNECT: ("disconnect", True),
}


class ProtocolHandlerException(Exception):
    pass


class ProtocolHandler:
    """
    Class implementing the MQTT communication protocol using async features
    """

    _got_packet: anyio.abc.Event = None

    def __init__(self, plugins_manager: PluginManager, session: Session = None):
        self.logger = logging.getLogger(__name__ + "." + self.__class__.__name__)
        if session:
            self._init_session(session)
        else:
            self.session = None
        self.stream = None
        self.plugins_manager = plugins_manager
        self._tg = plugins_manager._tg

        self._reader_task = None
        self._sender_task = None
        self._reader_stopped = anyio.Event()
        self._sender_stopped = anyio.Event()
        self._send_q = create_queue(10)

        self._puback_waiters = dict()
        self._pubrec_waiters = dict()
        self._pubrel_waiters = dict()
        self._pubcomp_waiters = dict()

        self._disconnecting = False
        self._disconnect_waiter = None
        self._write_lock = anyio.Lock()

    def _init_session(self, session: Session):
        assert session
        log = logging.getLogger(__name__)
        self.session = session
        self.logger = logging.LoggerAdapter(log, {"client_id": self.session.client_id})
        self.keepalive_timeout = self.session.keep_alive
        if self.keepalive_timeout <= 0:
            self.keepalive_timeout = None

    async def attach(self, session, stream: StreamAdapter):
        if self.session:
            raise ProtocolHandlerException("Handler is already attached to a session")
        self._init_session(session)
        self.stream = stream
        evt = anyio.Event()
        self._tg.start_soon(self._sender_loop, evt)
        await evt.wait()

    async def detach(self):
        self.session = None
        self.stream = None

    def _is_attached(self):
        return self.session is not None

    async def start(self):
        self._disconnect_waiter = anyio.Event()
        if not self._is_attached():
            raise ProtocolHandlerException("Handler is not attached to a stream")
        evt = anyio.Event()
        self._tg.start_soon(self._reader_loop, evt)
        await evt.wait()

        self.logger.debug("Handler tasks started")
        await self._retry_deliveries()
        self.logger.debug(
            "%s %s ready",
            "Broker" if "Broker" in type(self).__name__ else "Client",
            self.session.client_id if self.session else "?",
        )
        if self._reader_task is None:
            return
        try:
            self._reader_task.start_soon(self._timeout_loop)
        except RuntimeError:
            # This can happen when stuff overlaps
            pass

    async def stop(self):
        # Stop messages flow waiter
        self.logger.debug(
            "%s %s stopping",
            "Broker" if "Broker" in type(self).__name__ else "Client",
            self.session.client_id if self.session else "?",
        )
        await self._stop_waiters()
        t, self._reader_task = self._reader_task, None
        if t:
            self.logger.debug("waiting for reader %s to be stopped", t)
            t.cancel_scope.cancel()
            await self._reader_stopped.wait()
        t, self._sender_task = self._sender_task, None
        if t:
            self.logger.debug("waiting for sender %s to be stopped", t)
            await self._send_q.put(None)
            await self._sender_stopped.wait()
        self.logger.debug("closing writer")
        if self.stream is not None:
            await self.stream.close()
        if self._disconnect_waiter is not None:
            self._disconnect_waiter.set()
        self.logger.debug("closed writer")

    async def _stop_waiters(self):
        if len(self._puback_waiters):
            self.logger.debug("Stopping %d puback waiters", len(self._puback_waiters))
        if len(self._pubcomp_waiters):
            self.logger.debug("Stopping %d pucomp waiters", len(self._pubcomp_waiters))
        if len(self._pubrec_waiters):
            self.logger.debug("Stopping %d purec waiters", len(self._pubrec_waiters))
        if len(self._pubrel_waiters):
            self.logger.debug("Stopping %d purel waiters", len(self._pubrel_waiters))
        for waiter in itertools.chain(
            self._puback_waiters.values(),
            self._pubcomp_waiters.values(),
            self._pubrec_waiters.values(),
            self._pubrel_waiters.values(),
        ):
            with contextlib.suppress(InvalidStateError):
                await waiter.cancel()

    async def _retry_deliveries(self):
        """
        Handle [MQTT-4.4.0-1] by resending PUBLISH and PUBREL messages for pending out messages
        :return:
        """
        done = pending = 0
        self.logger.debug("Begin messages delivery retries")

        async def process_one(message):
            with anyio.move_on_after(10):
                with contextlib.suppress(CancelledError):
                    await self._handle_message_flow(message)

                nonlocal done
                done += 1  # pylint: disable=undefined-variable  ## fixed in 2.5

        async with anyio.create_task_group() as tg:
            for message in itertools.chain(
                self.session.inflight_in.values(),
                self.session.inflight_out.values(),
            ):
                pending += 1
                tg.start_soon(process_one, message)
        pending -= done

        self.logger.debug("%d messages redelivered", done)
        self.logger.debug("%d messages not redelivered due to timeout", pending)
        self.logger.debug("End messages delivery retries")

    async def mqtt_publish(self, topic, data, qos, retain):
        """
        Sends a MQTT publish message and manages messages flows.
        This methods doesn't return until the message has been acknowledged by receiver or timeout occur
        :param topic: MQTT topic to publish
        :param data:  data to send on topic
        :param qos: quality of service to use for message flow. Can be QOS_0, QOS_1 or QOS_2
        :param retain: retain message flag
        :param ack_timeout: acknowledge timeout. If set, this method will return a TimeOut error if the acknowledgment
        is not completed before ack_timeout second
        :return: ApplicationMessage used during inflight operations
        """
        packet_id = self.session.next_packet_id if qos in (QOS_1, QOS_2) else None

        message = OutgoingApplicationMessage(packet_id, topic, qos, data, retain)
        await self._handle_message_flow(message)

        return message

    async def _handle_message_flow(self, app_message):
        """
        Handle protocol flow for incoming and outgoing messages, depending on service level and according to MQTT
        spec. paragraph 4.3-Quality of Service levels and protocol flows
        :param app_message: PublishMessage to handle
        :return: nothing.
        """
        try:
            if app_message.qos == QOS_0:
                await self._handle_qos0_message_flow(app_message)
            elif app_message.qos == QOS_1:
                await self._handle_qos1_message_flow(app_message)
            elif app_message.qos == QOS_2:
                await self._handle_qos2_message_flow(app_message)
            else:
                raise MoatMQTTException("Unexcepted QOS value '%d" % str(app_message.qos))
        except CancelledError:
            pass

    async def _handle_qos0_message_flow(self, app_message):
        """
        Handle QOS_0 application message acknowledgment
        For incoming messages, this method stores the message
        For outgoing messages, this methods sends PUBLISH
        :param app_message:
        :return:
        """
        assert app_message.qos == QOS_0
        if app_message.direction == OUTGOING:
            packet = app_message.build_publish_packet()
            # Send PUBLISH packet
            await self._send_packet(packet)
            app_message.publish_packet = packet
        elif app_message.direction == INCOMING:
            if app_message.publish_packet.dup_flag:
                self.logger.warning(
                    "[MQTT-3.3.1-2] DUP flag must set to 0 for QOS 0 message. Message ignored: %r",
                    app_message.publish_packet,
                )
            else:
                await self.session.put_message(app_message)

    async def _handle_qos1_message_flow(self, app_message):
        """
        Handle QOS_1 application message acknowledgment
        For incoming messages, this method stores the message and reply with PUBACK
        For outgoing messages, this methods sends PUBLISH and waits for the corresponding PUBACK
        :param app_message:
        :return:
        """
        assert app_message.qos == QOS_1
        if app_message.puback_packet:
            raise MoatMQTTException(
                "Message '%d' has already been acknowledged" % app_message.packet_id,
            )
        if app_message.direction == OUTGOING:
            if app_message.packet_id not in self.session.inflight_out:
                # Store message in session
                self.session.inflight_out[app_message.packet_id] = app_message
            if app_message.publish_packet is not None:
                # A Publish packet has already been sent, this is a retry
                publish_packet = app_message.build_publish_packet(dup=True)
            else:
                publish_packet = app_message.build_publish_packet()

            # Wait for puback
            waiter = Future()
            self._puback_waiters[app_message.packet_id] = waiter
            # Send PUBLISH packet
            try:
                await self._send_packet(publish_packet)
                app_message.publish_packet = publish_packet
                app_message.puback_packet = await waiter.get()
            finally:
                del self._puback_waiters[app_message.packet_id]

            # Discard inflight message
            del self.session.inflight_out[app_message.packet_id]
        elif app_message.direction == INCOMING:
            # Initiate delivery
            self.logger.debug("Add message to delivery")
            await self.session.put_message(app_message)
            # Send PUBACK
            puback = PubackPacket.build(app_message.packet_id)
            await self._send_packet(puback)
            app_message.puback_packet = puback

    async def _handle_qos2_message_flow(self, app_message):
        """
        Handle QOS_2 application message acknowledgment
        For incoming messages, this method stores the message, sends PUBREC, waits for PUBREL, initiate delivery
        and send PUBCOMP
        For outgoing messages, this methods sends PUBLISH, waits for PUBREC, discards messages and wait for PUBCOMP
        :param app_message:
        :return:
        """
        assert app_message.qos == QOS_2
        if app_message.direction == OUTGOING:
            if app_message.pubrel_packet and app_message.pubcomp_packet:
                raise MoatMQTTException(
                    "Message '%d' has already been acknowledged" % app_message.packet_id,
                )
            if not app_message.pubrel_packet:
                # Store message
                if app_message.publish_packet is not None:
                    # This is a retry flow, no need to store just check the message exists in session
                    if app_message.packet_id not in self.session.inflight_out:
                        raise MoatMQTTException(
                            "Unknown inflight message '%d' in session" % app_message.packet_id,
                        )
                    publish_packet = app_message.build_publish_packet(dup=True)
                else:
                    # Store message in session
                    self.session.inflight_out[app_message.packet_id] = app_message
                    publish_packet = app_message.build_publish_packet()

                # Wait PUBREC
                if app_message.packet_id in self._pubrec_waiters:
                    # PUBREC waiter already exists for this packet ID
                    self.logger.warning(
                        "Can't add PUBREC waiter, a waiter already exists for message Id '%s'",
                        app_message.packet_id,
                    )
                    raise MoatMQTTException(app_message)
                waiter = Future()
                self._pubrec_waiters[app_message.packet_id] = waiter
                # Send PUBLISH packet
                try:
                    await self._send_packet(publish_packet)
                    app_message.publish_packet = publish_packet
                    app_message.pubrec_packet = await waiter.get()
                finally:
                    del self._pubrec_waiters[app_message.packet_id]

            if not app_message.pubcomp_packet:
                # Wait for PUBCOMP
                waiter = Future()
                self._pubcomp_waiters[app_message.packet_id] = waiter
                # Send pubrel
                try:
                    app_message.pubrel_packet = PubrelPacket.build(app_message.packet_id)
                    await self._send_packet(app_message.pubrel_packet)
                    app_message.pubcomp_packet = await waiter.get()
                finally:
                    del self._pubcomp_waiters[app_message.packet_id]
            # Discard inflight message
            del self.session.inflight_out[app_message.packet_id]
        elif app_message.direction == INCOMING:
            self.session.inflight_in[app_message.packet_id] = app_message
            # Wait PUBREL
            if (
                app_message.packet_id in self._pubrel_waiters
                and not self._pubrel_waiters[app_message.packet_id].done()
            ):
                # PUBREL waiter already exists for this packet ID
                self.logger.warning(
                    "A waiter already exists for message Id '%s', canceling it",
                    app_message.packet_id,
                )
                await self._pubrel_waiters[app_message.packet_id].cancel()
            waiter = Future()
            self._pubrel_waiters[app_message.packet_id] = waiter
            # Send pubrec
            try:
                pubrec_packet = PubrecPacket.build(app_message.packet_id)
                await self._send_packet(pubrec_packet)
                app_message.pubrec_packet = pubrec_packet
                app_message.pubrel_packet = await waiter.get()
            finally:
                if self._pubrel_waiters.get(app_message.packet_id) is waiter:
                    del self._pubrel_waiters[app_message.packet_id]
            # Initiate delivery and discard message
            await self.session.put_message(app_message)
            del self.session.inflight_in[app_message.packet_id]
            # Send pubcomp
            pubcomp_packet = PubcompPacket.build(app_message.packet_id)
            await self._send_packet(pubcomp_packet)
            app_message.pubcomp_packet = pubcomp_packet

    async def _timeout_loop(self):
        keepalive_timeout = self.session.keep_alive
        if keepalive_timeout <= 0:
            keepalive_timeout = None

        while True:
            while True:
                with anyio.move_on_after(keepalive_timeout):
                    await self._got_packet.wait()
                    self._got_packet = anyio.Event()
                    continue
            self.logger.debug(
                "%s Input stream read timeout",
                self.session.client_id if self.session else "?",
            )
            await self.handle_read_timeout()

    async def _reader_loop(self, evt):
        self.logger.debug("%s Starting reader coro", self.session.client_id)
        self._got_packet = anyio.Event()

        try:
            async with anyio.create_task_group() as tg:
                self._reader_task = tg
                evt.set()
                while True:
                    try:
                        fixed_header = await MQTTFixedHeader.from_stream(self.stream)
                        if fixed_header is None:
                            self.logger.debug(
                                "%s No more data (EOF received), stopping reader coro",
                                self.session.client_id,
                            )
                            break

                        if (
                            fixed_header.packet_type == RESERVED_0
                            or fixed_header.packet_type == RESERVED_15
                        ):
                            self.logger.warning(
                                "%s Received reserved packet, which is forbidden: closing connection",
                                self.session.client_id,
                            )
                            await self.handle_connection_closed()
                            break

                        cls = packet_class(fixed_header)
                        packet = await cls.from_stream(self.stream, fixed_header=fixed_header)
                        self.logger.debug(
                            "< %s %r",
                            "B" if "Broker" in type(self).__name__ else "C",
                            packet,
                        )
                        self._got_packet.set()  # don't wait for the body
                        await self.plugins_manager.fire_event(
                            EVENT_MQTT_PACKET_RECEIVED,
                            packet=packet,
                            session=self.session,
                        )
                        try:
                            pt, direct = PACKET_TYPES[packet.fixed_header.packet_type]
                            fn = getattr(self, "handle_" + pt)
                        except (KeyError, AttributeError):
                            self.logger.warning(
                                "%s Unhandled packet type: %s",
                                self.session.client_id,
                                packet.fixed_header.packet_type,
                            )
                        else:
                            try:
                                if direct:
                                    await fn(packet)
                                else:
                                    tg.start_soon(fn, packet)
                            except StopAsyncIteration:
                                break

                    except MQTTException:
                        self.logger.debug("Message discarded")
                    except NoDataException:
                        self.logger.debug("%s No data available", self.session.client_id)
                        break  # XXX
                    except (
                        anyio.BrokenResourceError,
                        anyio.ClosedResourceError,
                        anyio.EndOfStream,
                    ):
                        self.logger.debug("%s No data available", self.session.client_id)
                        break

                    except anyio.get_cancelled_exc_class():
                        self.logger.debug("%s CANCEL", type(self).__name__)
                        raise
                    except BaseException as e:
                        self.logger.warning(
                            "%s Unhandled exception in reader coro",
                            type(self).__name__,
                            exc_info=e,
                        )
                        raise
                # tg.cancel_scope.cancel()  # XXX is that needed?
        finally:
            with anyio.fail_after(2, shield=True):
                self.logger.debug(
                    "%s %s coro stopped",
                    "Broker" if "Broker" in type(self).__name__ else "Client",
                    self.session.client_id if self.session else "?",
                )
                self._reader_stopped.set()
                if self._reader_task is not None:
                    self._reader_task = None
                    await self.handle_connection_closed()

    async def _send_packet(self, packet):
        await self._send_q.put(packet)

    async def _sender_loop(self, evt):
        keepalive_timeout = self.session.keep_alive
        if keepalive_timeout <= 0:
            keepalive_timeout = None

        try:
            with anyio.CancelScope() as scope:
                self._sender_task = scope
                evt.set()
                while True:
                    packet = None
                    with anyio.move_on_after(keepalive_timeout):
                        packet = await self._send_q.get()
                        if packet is None:  # closing
                            break
                    if packet is None:  # timeout
                        await self.handle_write_timeout()
                        continue
                    self.logger.debug(
                        "%s > %r",
                        "B" if "Broker" in type(self).__name__ else "C",
                        packet,
                    )
                    try:
                        await packet.to_stream(self.stream)
                    except (ClosedResourceError, BrokenResourceError, EndOfStream):
                        return
                    await self.plugins_manager.fire_event(
                        EVENT_MQTT_PACKET_SENT,
                        packet=packet,
                        session=self.session,
                    )
        except ConnectionResetError:
            await self.handle_connection_closed()
        except anyio.get_cancelled_exc_class():
            raise
        except BaseException as e:
            self.logger.warning("Unhandled exception", exc_info=e)
            raise
        finally:
            self._sender_stopped.set()
            self._sender_task = None

    async def handle_write_timeout(self):
        self.logger.debug("%s write timeout unhandled", self.session.client_id)

    async def handle_read_timeout(self):
        self.logger.debug("%s read timeout unhandled", self.session.client_id)

    async def handle_connack(self, connack: ConnackPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s CONNACK unhandled", self.session.client_id)

    async def handle_connect(self, connect: ConnectPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s CONNECT unhandled", self.session.client_id)

    async def handle_subscribe(self, subscribe: SubscribePacket):  # pylint: disable=unused-argument
        self.logger.debug("%s SUBSCRIBE unhandled", self.session.client_id)

    async def handle_unsubscribe(self, unsubscribe: UnsubscribePacket):  # pylint: disable=unused-argument
        self.logger.debug("%s UNSUBSCRIBE unhandled", self.session.client_id)

    async def handle_suback(self, suback: SubackPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s SUBACK unhandled", self.session.client_id)

    async def handle_unsuback(self, unsuback: UnsubackPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s UNSUBACK unhandled", self.session.client_id)

    async def handle_pingresp(self, pingresp: PingRespPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s PINGRESP unhandled", self.session.client_id)

    async def handle_pingreq(self, pingreq: PingReqPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s PINGREQ unhandled", self.session.client_id)

    async def _handle_disconnect(self, disconnect: DisconnectPacket):  # pylint: disable=unused-argument
        self.logger.debug("%s DISCONNECT unhandled", self.session.client_id)

    async def handle_disconnect(self, disconnect: DisconnectPacket):
        if not self._disconnecting:
            self._disconnecting = True
            self._tg.start_soon(self._handle_disconnect, disconnect)
        else:
            self.logger.debug("%s DISCONNECT ignored", self.session.client_id)
        raise StopAsyncIteration  # end of the line

    async def handle_connection_closed(self):
        self.logger.debug("%s Connection closed unhandled", self.session.client_id)

    async def handle_puback(self, puback: PubackPacket):
        packet_id = puback.variable_header.packet_id
        try:
            waiter = self._puback_waiters[packet_id]
            await waiter.set(puback)
        except KeyError:
            self.logger.warning("Received PUBACK for unknown pending message Id: '%d'", packet_id)
        except InvalidStateError:
            self.logger.warning("PUBACK waiter with Id '%d' already done", packet_id)

    async def handle_pubrec(self, pubrec: PubrecPacket):
        packet_id = pubrec.packet_id
        try:
            waiter = self._pubrec_waiters[packet_id]
            await waiter.set(pubrec)
        except KeyError:
            self.logger.warning(
                "Received PUBREC for unknown pending message with Id: %d",
                packet_id,
            )
        except InvalidStateError:
            self.logger.warning("PUBREC waiter with Id '%d' already done", packet_id)

    async def handle_pubcomp(self, pubcomp: PubcompPacket):
        packet_id = pubcomp.packet_id
        try:
            waiter = self._pubcomp_waiters[packet_id]
            await waiter.set(pubcomp)
        except KeyError:
            self.logger.warning(
                "Received PUBCOMP for unknown pending message with Id: %d",
                packet_id,
            )
        except InvalidStateError:
            self.logger.warning("PUBCOMP waiter with Id '%d' already done", packet_id)

    async def handle_pubrel(self, pubrel: PubrelPacket):
        packet_id = pubrel.packet_id
        try:
            waiter = self._pubrel_waiters[packet_id]
            await waiter.set(pubrel)
        except KeyError:
            self.logger.warning(
                "Received PUBREL for unknown pending message with Id: %d",
                packet_id,
            )
        except InvalidStateError:
            self.logger.warning("PUBREL waiter with Id '%d' already done", packet_id)

    async def handle_publish(self, publish_packet: PublishPacket):
        try:
            packet_id = publish_packet.variable_header.packet_id
            qos = publish_packet.qos

            incoming_message = IncomingApplicationMessage(
                packet_id,
                publish_packet.topic_name,
                qos,
                publish_packet.data,
                publish_packet.retain_flag,
            )
            incoming_message.publish_packet = publish_packet
            if incoming_message.qos == QOS_0:
                await self._handle_message_flow(incoming_message)
            else:
                self._reader_task.start_soon(self._handle_message_flow, incoming_message)

        #           if self.session is not None:
        #               self.logger.debug("Message queue size: %d", self.session._delivered_message_queue.qsize())
        except CancelledError:
            pass

    async def wait_disconnect(self):
        if self._disconnect_waiter is not None:
            return await self._disconnect_waiter.wait()
