#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

from threading import Thread
from http import server
import json

sys.path.append(".")
sys.path.append("..")
from components.utilities import Struct
from components.bugzilla import BugzillaProvider, CommentTemplates
from components.logging import SimpleLoggerConfig

TRY_REVISION = "this-is-my-try-link"


class MockBugzillaServer(server.BaseHTTPRequestHandler):
    def do_POST(self):
        expectedPath_file = "/bug?api_key=bob"
        size = int(self.headers.get('content-length'))
        content = json.loads(self.rfile.read(size).decode("utf-8"))

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        if expectedPath_file == self.path:
            expectedContent = {
                'version': "unspecified",
                'op_sys': "unspecified",

                'product': 'Core',
                'component': 'ImageLib',
                'type': "enhancement",
                'severity': "normal",
                'summary': 'Update dav1d to new version V1 from 2020-08-21 15:13:49',
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
            assert False, "Got a path %s I didn't expect" % self.path

    def do_PUT(self):
        expectedPath_comment = "/bug/123?api_key=bob"
        size = int(self.headers.get('content-length'))
        content = json.loads(self.rfile.read(size).decode("utf-8"))

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        if expectedPath_comment == self.path:
            assert 'id' in content
            assert 'comment' in content
            assert 'body' in content['comment']
            if 'flags' in content:
                assert content['comment']['body'] == "Test Flags"
                assert content['flags'][0]['name'] == 'needinfo'
                assert content['flags'][0]['status'] == '?'
                assert content['flags'][0]['requestee'] == 'Jon'
            elif 'assigned_to' in content:
                assert content['comment']['body'] == "Test Assignee"
                assert content['assigned_to'] == 'Jon'
            else:
                assert content['comment']['body'] == CommentTemplates.TRY_RUN_SUBMITTED(TRY_REVISION)

            self.wfile.write("{'bugs':[{'alias':null,'changes':{},'last_change_time':'2020-07-10T18:58:21Z','id':123}]}".replace("'", '"').encode())
        else:
            assert False, "Got a path %s I didn't expect" % self.path


class TestBugzillaProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.HTTPServer(('', 27489), MockBugzillaServer)
        cls.bugzillaProvider = BugzillaProvider({
            'General': {'env': 'dev'},
            'apikey': 'bob',
            'url': 'http://localhost:27489/',
        })
        cls.bugzillaProvider.update_config(SimpleLoggerConfig)
        t = Thread(target=cls.server.serve_forever)
        t.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def testFile(self):
        library = Struct(**{
            'name': 'dav1d',
            'bugzilla_product': 'Core',
            'bugzilla_component': 'ImageLib',
        })
        self.bugzillaProvider.file_bug(library, 'V1', '2020-08-21T15:13:49.000+02:00')

    def testComment(self):
        self.bugzillaProvider.comment_on_bug(
            123, CommentTemplates.TRY_RUN_SUBMITTED(TRY_REVISION))

        self.bugzillaProvider.comment_on_bug(
            123, "Test Assignee", assignee='Jon')

        self.bugzillaProvider.comment_on_bug(
            123, "Test Flags", needinfo='Jon')


if __name__ == '__main__':
    unittest.main(verbosity=0)
