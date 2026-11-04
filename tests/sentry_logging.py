#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import io
import gzip
import json
import random
import string
import sys
import threading
import unittest
import contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer

import sentry_sdk
from sentry_sdk.transport import Transport

sys.path.append(".")
sys.path.append("..")
from components.logging import (
    LogLevel, SentryLogger, LoggingSentryTransport, trim_sentry_event,
    SENTRY_MAX_EVENT_BYTES, SENTRY_MAX_COMPRESSED_EVENT_BYTES, SENTRY_MAX_BREADCRUMB_LENGTH, SENTRY_MAX_VALUE_LENGTH)

FAKE_DSN = "http://public@127.0.0.1:%d/1"


class RecordingTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.get_bytes())


class Always413(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(413)
        self.end_headers()

    def log_message(self, *args):
        pass


def random_text(length):
    return "".join(random.choices(string.ascii_letters + string.digits + " ", k=length))


class TestSentryLogging(unittest.TestCase):
    def setUp(self):
        random.seed(0)
        self.logger = SentryLogger({'sentry': True, 'sentry_config': {'url': 'unused'}})

    def tearDown(self):
        sentry_sdk.get_client().close()
        sentry_sdk.init()
        sentry_sdk.get_isolation_scope().clear_breadcrumbs()

    def _init_recording(self):
        transport = RecordingTransport()
        sentry_sdk.init(dsn=FAKE_DSN % 9, transport=transport, default_integrations=False,
                        max_breadcrumbs=5000, max_value_length=SENTRY_MAX_VALUE_LENGTH,
                        before_send=trim_sentry_event)
        sentry_sdk.get_isolation_scope().clear_breadcrumbs()
        return transport

    def _capture(self):
        try:
            raise Exception("Something went wrong")
        except Exception as e:
            sentry_sdk.capture_exception(e)

    def _breadcrumbs(self, event_bytes):
        return [b["message"] for b in json.loads(event_bytes)["breadcrumbs"]["values"]]

    def testShortBreadcrumbIsUnchanged(self):
        transport = self._init_recording()
        self.logger.log("short", "message", level=LogLevel.Info, category="Test")
        self._capture()
        self.assertEqual(self._breadcrumbs(transport.events[0]), ["short message"])

    def testLongBreadcrumbKeepsBeginningAndEnd(self):
        transport = self._init_recording()
        message = "BEGIN" + random_text(100000) + "END"
        self.logger.log(message, level=LogLevel.Info, category="Test")
        self._capture()

        [crumb] = self._breadcrumbs(transport.events[0])
        self.assertTrue(crumb.startswith("BEGIN"))
        self.assertTrue(crumb.endswith("END"))
        self.assertIn("characters omitted", crumb)
        self.assertLess(len(crumb), SENTRY_MAX_BREADCRUMB_LENGTH + 100)

    def testSmallEventIsUntouched(self):
        transport = self._init_recording()
        for i in range(100):
            self.logger.log("line %d" % i, level=LogLevel.Info, category="Test")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self._capture()

        self.assertEqual(len(self._breadcrumbs(transport.events[0])), 100)
        self.assertEqual(output.getvalue(), "")

    def _assertTrimmedToFit(self, line_length):
        transport = self._init_recording()
        for i in range(5000):
            self.logger.log("line %d %s" % (i, random_text(line_length)), level=LogLevel.Info, category="Test")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self._capture()

        event = transport.events[0]
        self.assertLessEqual(len(event), SENTRY_MAX_EVENT_BYTES)
        self.assertLessEqual(len(gzip.compress(event)), SENTRY_MAX_COMPRESSED_EVENT_BYTES)
        crumbs = self._breadcrumbs(event)
        self.assertGreater(len(crumbs), 0)
        self.assertLess(len(crumbs), 5000)
        self.assertTrue(crumbs[-1].startswith("line 4999 "), "The newest breadcrumbs should be kept")
        self.assertIn("Dropped the oldest %d of 5000 breadcrumbs" % (5000 - len(crumbs)), output.getvalue())
        return crumbs

    def testOversizedEventIsTrimmed(self):
        # Random text compresses poorly, so this exceeds the compressed limit first
        self._assertTrimmedToFit(1000)

    def testOversizedCompressibleEventIsTrimmed(self):
        # Long runs of repeated lines compress well, so this exceeds the uncompressed limit first
        transport = self._init_recording()
        line = random_text(400)
        for i in range(5000):
            self.logger.log("line %d %s" % (i, line), level=LogLevel.Info, category="Test")
        with contextlib.redirect_stdout(io.StringIO()):
            self._capture()

        event = transport.events[0]
        self.assertLessEqual(len(event), SENTRY_MAX_EVENT_BYTES)
        self.assertGreater(len(event), SENTRY_MAX_EVENT_BYTES * 0.9)
        self.assertTrue(self._breadcrumbs(event)[-1].startswith("line 4999 "))

    def testRejectedEventIsLogged(self):
        server = HTTPServer(("127.0.0.1", 0), Always413)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                sentry_sdk.init(dsn=FAKE_DSN % server.server_port, transport=LoggingSentryTransport,
                                default_integrations=False)
                sentry_sdk.capture_message("hello")
                sentry_sdk.flush(timeout=10)
                sentry_sdk.get_client().close()
            self.assertIn("Sentry rejected an event because it was too large (HTTP 413)", output.getvalue())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main(verbosity=0)
