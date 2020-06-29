#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

from threading import Thread
from http import server
import json

sys.path.append("..")
from components.utilities import Struct
from components.dbmodels import JOBSTATUS
from components.bugzilla import BugzillaProvider

from tests.mock_logger import TestLoggerConfig


class MockBugzillaServer(server.BaseHTTPRequestHandler):
    def do_POST(self):
        expectedPath_comment = "/bug/123/comment?api_key=bob"
        expectedPath_file = "/bug?api_key=bob"
        size = int(self.headers.get('content-length'))
        content = json.loads(self.rfile.read(size).decode("utf-8"))

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        if expectedPath_comment == self.path:
            assert 'comment' in content
            assert content['comment'] == "I've submitted a try run for this commit: https://treeherder.mozilla.org/#/jobs?repo=try&revision=this-is-my-try-link"

            self.wfile.write("{\"id\":456}".encode())
        elif expectedPath_file == self.path:
            expectedContent = {
                'version': "unspecified",
                'op_sys': "unspecified",

                'product': 'Core',
                'component': 'ImageLib',
                'type': "enhancement",
                'severity': "normal",
                'summary': 'Update dav1d to new version V1',
                'description': '',
                'whiteboard': '[3pl-filed]',
                'cc': ['tom@mozilla.com']
            }
            for k in expectedContent:
                assert k in content
                assert expectedContent[k] == content[k]
            for k in content:
                assert k in expectedContent

            self.wfile.write("{\"id\":456}".encode())
        else:
            assert False, "Got a path I didn't expect"


class TestBugzillaProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.HTTPServer(('', 27489), MockBugzillaServer)
        cls.bugzillaProvider = BugzillaProvider({
            'General': {'env': 'dev'},
            'apikey': 'bob',
            'url': 'http://localhost:27489/',
        })
        cls.bugzillaProvider.update_config(TestLoggerConfig)

    @classmethod
    def tearDownClass(cls):
        cls.server.server_close()

    def testFile(self):
        library = Struct(**{
            'shortname': 'dav1d',
            'bugzilla_product': 'Core',
            'bugzilla_component': 'ImageLib',
        })
        t = Thread(target=self.server.handle_request)
        t.start()
        self.bugzillaProvider.file_bug(library, 'V1')
        t.join()

    def testComment(self):
        t = Thread(target=self.server.handle_request)
        t.start()
        self.bugzillaProvider.comment_on_bug(
            123, JOBSTATUS.AWAITING_TRY_RESULTS, "this-is-my-try-link")
        t.join()


if __name__ == '__main__':
    unittest.main()
