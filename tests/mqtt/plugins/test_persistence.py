# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations

import logging
import os
import sqlite3
import unittest

from moat.mqtt.plugins.manager import BaseContext
from moat.mqtt.plugins.persistence import SQLitePlugin


class TestSQLitePlugin(unittest.TestCase):
    def test_create_tables(self):
        dbfile = os.path.join(os.path.dirname(os.path.realpath(__file__)), "test.db")
        context = BaseContext()
        context.logger = logging.getLogger(__name__)
        context.config = {"persistence": {"file": dbfile}}
        SQLitePlugin(context)

        conn = sqlite3.connect(dbfile)
        cursor = conn.cursor()
        rows = cursor.execute("SELECT name FROM sqlite_master where type = 'table'")
        tables = []
        for row in rows:
            tables.append(row[0])
        assert "session" in tables

    # def test_save_session(self):
    #     dbfile = os.path.join(os.path.dirname(os.path.realpath(__file__)), "test.db")
    #     context = BaseContext()
    #     context.logger = logging.getLogger(__name__)
    #     context.config = {
    #         'persistence': {
    #             'file': dbfile
    #         }
    #     }
    #     sql_plugin = SQLitePlugin(context)
    #     s = Session()
    #     s.client_id = 'test_save_session'
    #     ret = asyncio.run(sql_plugin.save_session(session=s))
    #
    #     conn = sqlite3.connect(dbfile)
    #     cursor = conn.cursor()
    #     row = cursor.execute("SELECT client_id FROM session where client_id = 'test_save_session'").fetchone()
    #     self.assertTrue(len(row) == 1)
    #     self.assertEqual(row[0], s.client_id)
