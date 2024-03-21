#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re
import sys
import unittest

from threading import Thread
from http import server
import json

sys.path.append(".")
sys.path.append("..")
from components.utilities import Struct, string_date_to_uniform_string_date
from components.bugzilla import BugzillaProvider, CommentTemplates
from components.logging import SimpleLoggerConfig

from apis.bugzilla_api import task_id_whiteboard

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
                'summary': 'Update dav1d to new version V1 from 2020-08-21 15:13:49',
                'description': '',
                'whiteboard': '[3pl-filed]' + task_id_whiteboard(),
                'cc': ['tom@mozilla.com', 'fbraun@mozilla.com', 'additional@example.com'],
                'flags': [{'name': 'needinfo', 'status': '?', 'requestee': 'needinfo@example.com'}],
                'depends_on': 110,
                'blocks': 120,
                'see_also': 210,
                'cf_status_firefox88': 'affected',
                'groups': ['mozilla-employee-confidential']
            }
            for k in expectedContent:
                assert k in content, k + " not in content"
                assert expectedContent[k] == content[k], str(k) + " is " + str(content[k]) + " not " + str(expectedContent[k])
            for k in content:
                assert k in expectedContent, "Unexpected " + str(k) + " in content"

            self.wfile.write("{\"id\":456}".encode())
        else:
            assert False, "Got a path %s I didn't expect" % self.path

    def do_GET(self):
        expectedPath_find = "/bug?resolution=---&id=1,2,3&include_fields=id"

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        if expectedPath_find == self.path:
            self.wfile.write('{"bugs":[{"id":2}]}'.encode())
        else:
            assert False, "Got a path %s I didn't expect" % self.path

    def do_PUT(self):
        expectedPath_comment = "/bug/123"
        expectedPath_status = "/bug/456?api_key=bob"
        expectedPath_close = "/bug/789"
        size = int(self.headers.get('content-length'))
        content = json.loads(self.rfile.read(size).decode("utf-8"))
        bug_id = re.match(r"/bug/([0-9]+)\?api_key=bob", self.path).groups(0)[0]

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        if expectedPath_comment in self.path:
            assert 'id' in content
            assert 'comment' in content
            assert len(content['comment']['body']) < 65535
            assert 'comment_tags' in content
            assert 'body' in content['comment']
            if bug_id == "1234":
                assert content['comment']['body'] == CommentTemplates.TRY_RUN_SUBMITTED(TRY_REVISION)
            elif bug_id == "1236":
                assert 'flags' in content
                assert content['comment']['body'] == "Test Flags"
                assert content['flags'][0]['name'] == 'needinfo'
                assert content['flags'][0]['status'] == '?'
                assert content['flags'][0]['requestee'] == 'Jon'
            elif bug_id == "1235":
                assert 'assigned_to' in content
                assert content['comment']['body'] == "Test Assignee"
                assert content['assigned_to'] == 'Jon'

            self.wfile.write(("{'bugs':[{'alias':null,'changes':{},'last_change_time':'2020-07-10T18:58:21Z','id':" + bug_id + "}]}").replace("'", '"').encode())
        elif expectedPath_status == self.path:
            assert 'id' in content
            assert 'cf_status_firefox76' in content
            assert content['cf_status_firefox76'] == 'affected'

            self.wfile.write("{'bugs':[{'alias':null,'changes':{},'last_change_time':'2020-07-10T18:58:21Z','id':456}]}".replace("'", '"').encode())
        elif expectedPath_close in self.path:
            assert 'id' in content
            assert 'status' in content
            assert content['status'] == 'RESOLVED'
            assert 'resolution' in content
            assert 'comment' in content
            assert 'comment_tags' in content
            assert 'body' in content['comment']

            if bug_id == "7890":
                assert content['resolution'] == 'WONTFIX'
                assert content['comment']['body'] == "Hello World"

            elif bug_id == "7891":
                assert content['resolution'] == 'DUPLICATE'
                assert content['comment']['body'] == "Hello Earth"

                assert 'dup_id' in content
                assert content['dup_id'] == 12345

            self.wfile.write(("{'bugs':[{'alias':null,'changes':{},'last_change_time':'2020-07-10T18:58:21Z','id':" + bug_id + "}]}").replace("'", '"').encode())
        else:
            assert False, "Got a path %s I didn't expect" % self.path


class TestBugzillaProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.HTTPServer(('', 27489), MockBugzillaServer)
        cls.bugzillaProvider = BugzillaProvider({
            'General': {
                'env': 'dev',
                'ff-version': 88,
                'repo': 'https://hg.mozilla.org/mozilla-central'
            },
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
        self.bugzillaProvider.file_bug(library, CommentTemplates.UPDATE_SUMMARY(library, 'V1', string_date_to_uniform_string_date('2020-08-21T15:13:49.000+02:00')), "", ['additional@example.com'], ['needinfo@example.com'], 210, 110, 120, moco_confidential=True)

    def testComment(self):
        self.bugzillaProvider.comment_on_bug(
            1234, CommentTemplates.TRY_RUN_SUBMITTED(TRY_REVISION))

        self.bugzillaProvider.comment_on_bug(
            1235, "Test Assignee", assignee='Jon')

        self.bugzillaProvider.comment_on_bug(
            1236, "Test Flags", needinfo='Jon')

        self.bugzillaProvider.comment_on_bug(
            1237, "X" * 70000, assignee='Jon')

    def testStatus(self):
        self.bugzillaProvider.mark_ff_version_affected(456, 76)

    def testGet(self):
        self.assertEqual([2], self.bugzillaProvider.find_open_bugs([1, 2, 3]))

    def testClose(self):
        self.bugzillaProvider.wontfix_bug(7890, "Hello World")
        self.bugzillaProvider.dupe_bug(7891, "Hello Earth", 12345)


if __name__ == '__main__':
    unittest.main(verbosity=0)
