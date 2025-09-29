# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations

import logging
import os
import unittest

from tests.moat_mqtt import anyio_run

from moat.mqtt.plugins.authentication import AnonymousAuthPlugin, FileAuthPlugin
from moat.mqtt.plugins.manager import BaseContext
from moat.mqtt.session import Session


class TestAnonymousAuthPlugin(unittest.TestCase):  # noqa: D101
    def test_allow_anonymous(self):  # noqa: D102
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {"auth": {"allow-anonymous": True}}

        async def coro():
            s = Session(None)
            s.username = ""
            auth_plugin = AnonymousAuthPlugin(context)
            ret = await auth_plugin.authenticate(session=s)
            assert ret

        anyio_run(coro)

    def test_disallow_anonymous(self):  # noqa: D102
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {"auth": {"allow-anonymous": False}}

        async def coro():
            s = Session(None)
            s.username = ""
            auth_plugin = AnonymousAuthPlugin(context)
            ret = await auth_plugin.authenticate(session=s)
            assert not ret

        anyio_run(coro)

    def test_allow_nonanonymous(self):  # noqa: D102
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {"auth": {"allow-anonymous": False}}

        async def coro():
            s = Session(None)
            s.username = "test"
            auth_plugin = AnonymousAuthPlugin(context)
            ret = await auth_plugin.authenticate(session=s)
            assert ret

        anyio_run(coro)


class TestFileAuthPlugin(unittest.TestCase):  # noqa: D101
    def test_allow(self):  # noqa: D102
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {
            "auth": {
                "password-file": os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "passwd",
                ),
            },
        }

        async def coro():
            s = Session(None)
            s.username = "user"
            s.password = "test"
            auth_plugin = FileAuthPlugin(context)
            ret = await auth_plugin.authenticate(session=s)
            assert ret

        anyio_run(coro)

    def test_wrong_password(self):  # noqa: D102
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {
            "auth": {
                "password-file": os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "passwd",
                ),
            },
        }

        async def coro():
            s = Session(None)
            s.username = "user"
            s.password = "wrong password"
            auth_plugin = FileAuthPlugin(context)
            ret = await auth_plugin.authenticate(session=s)
            assert not ret

        anyio_run(coro)

    def test_unknown_password(self):  # noqa: D102
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {
            "auth": {
                "password-file": os.path.join(
                    os.path.dirname(os.path.realpath(__file__)),
                    "passwd",
                ),
            },
        }

        async def coro():
            s = Session(None)
            s.username = "some user"
            s.password = "some password"
            auth_plugin = FileAuthPlugin(context)
            ret = await auth_plugin.authenticate(session=s)
            assert not ret

        anyio_run(coro)
