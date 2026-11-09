#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
import sys
import unittest
import urllib.parse

from threading import Thread
from http import server
import json

sys.path.append(".")
sys.path.append("..")
from components.utilities import Struct, string_date_to_uniform_string_date
from components.bugzilla import BugzillaProvider, CommentTemplates
from components.logging import SimpleLoggerConfig

import components.utilities
from apis.bugzilla_api import task_id_whiteboard, CommentRejectedError

TRY_REVISION = "this-is-my-try-link"


class MockBugzillaServer(server.BaseHTTPRequestHandler):
    closed_bug_ids = []
    filed_bugs = []
    received_comments = {}
    # Writes that failed with a gateway error, but that Bugzilla processed anyway
    processed_bugs = {}
    processed_comments = {}
    comment_gets = {}

    def _gateway_error(self, status):
        self.send_response(status)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"stream timeout")

    def do_POST(self):
        expectedPath_file = "/bug?api_key=bob"
        size = int(self.headers.get('content-length'))
        content = json.loads(self.rfile.read(size).decode("utf-8"))

        # Filing fails with a 502 the first time; 'gateway-processed' was filed anyway
        if 'gateway-' in content.get('summary', ''):
            MockBugzillaServer.filed_bugs.append(content)
            attempts = len([b for b in MockBugzillaServer.filed_bugs if b['summary'] == content['summary']])
            if attempts == 1:
                if 'gateway-processed' in content['summary']:
                    MockBugzillaServer.processed_bugs[content['summary']] = 460
                self._gateway_error(502)
                return
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":459}')
            return

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        MockBugzillaServer.filed_bugs.append(content)
        if content['component'] == 'Missing Component':
            self.wfile.write(json.dumps({'error': True, 'code': 51, 'message': "There is no component named 'Missing Component' in the 'Core' product."}).encode())
        elif content['product'] == 'Core' and content['component'] == 'General':
            self.wfile.write("{\"id\":457}".encode())
        elif content['component'] == 'Mach Vendor & Updatebot':
            if 'broken' in content['summary']:
                self.wfile.write(json.dumps({'error': True, 'code': 100, 'message': "Something went wrong."}).encode())
            else:
                self.wfile.write("{\"id\":458}".encode())
        elif expectedPath_file == self.path:
            expectedContent = {
                'version': "unspecified",
                'op_sys': "unspecified",

                'product': 'Core',
                'component': 'ImageLib',
                'type': "enhancement",
                'summary': 'Update dav1d to new version V1 from 2020-08-21 13:13:49 UTC',
                'description': '',
                'whiteboard': '[3pl-filed]' + task_id_whiteboard(),
                'cc': ['tom@mozilla.com', 'jewilde@mozilla.com', 'additional@example.com'],
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
        expectedPath_find = "/bug?resolution=---&id="
        expectedPath_comments_autoland = "/bug/7892/comment"
        expectedPath_comments_github = "/bug/7893/comment"
        expectedPath_comments_mozilla_central = "/bug/7894/comment"

        # Checking bug 1233's comments fails with a gateway error the first time
        if self.path.startswith("/bug/1233/comment"):
            MockBugzillaServer.comment_gets["1233"] = MockBugzillaServer.comment_gets.get("1233", 0) + 1
            if MockBugzillaServer.comment_gets["1233"] == 1:
                self._gateway_error(504)
                return

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get('f1') == ['status_whiteboard']:
            # Looking for a bug filed by this task with this summary
            bug_id = MockBugzillaServer.processed_bugs.get(query['v2'][0])
            self.wfile.write(json.dumps({'bugs': [{'id': bug_id}] if bug_id else []}).encode())
        elif re.match(r"/bug/(1231|1233|7895)/comment", self.path):
            bug_id = re.match(r"/bug/([0-9]+)/", self.path).group(1)
            self.wfile.write(json.dumps({'bugs': {bug_id: {'comments': MockBugzillaServer.processed_comments.get(bug_id, [])}}}).encode())
        elif expectedPath_find in self.path:
            self.wfile.write('{"bugs":[{"id":2,"assigned_to_detail":{"id":578488,"email":"tom@mozilla.com","real_name":"Tom Ritter [:tjr]","name":"tom@mozilla.com","nick":"tjr"},"assigned_to":"tom@mozilla.com"}],"faults":[]}'.encode())
        elif expectedPath_comments_autoland == self.path:
            self.wfile.write('{"bugs":{"7892":{"comments":[{"text":"landing: https://hg.mozilla.org/integration/autoland/rev/abc123"}]}}}'.encode())
        elif expectedPath_comments_github == self.path:
            self.wfile.write('{"bugs":{"7893":{"comments":[{"text":"landing: https://github.com/mozilla-firefox/firefox/commit/abc123"}]}}}'.encode())
        elif expectedPath_comments_mozilla_central == self.path:
            self.wfile.write('{"bugs":{"7894":{"comments":[{"text":"landing: https://hg.mozilla.org/mozilla-central/rev/abc123"}]}}}'.encode())
        elif "/comment" in self.path:
            self.wfile.write('{"bugs":{"7891":{"comments":[{"text":"no autoland links here"}]}}}'.encode())
        else:
            assert False, "Got a path %s I didn't expect" % self.path

    def do_PUT(self):
        expectedPath_comment = "/bug/123"
        expectedPath_status = "/bug/456?api_key=bob"
        expectedPath_close = "/bug/789"
        size = int(self.headers.get('content-length'))
        content = json.loads(self.rfile.read(size).decode("utf-8"))
        bug_id = re.match(r"/bug/([0-9]+)\?api_key=bob", self.path).groups(0)[0]
        MockBugzillaServer.received_comments.setdefault(bug_id, []).append(content)

        # Gateway errors: bugs 1230 and 1233 fail once, bug 1231 fails but is processed
        # anyway, bug 1232 always fails, and closing bug 7895 fails but is processed anyway
        attempts = len(MockBugzillaServer.received_comments[bug_id])
        if bug_id in ("1231", "7895"):
            MockBugzillaServer.processed_comments.setdefault(bug_id, []).append(
                {'text': content['comment']['body'], 'tags': content['comment_tags']})
        if (bug_id in ("1230", "1233") and attempts == 1) or bug_id in ("1231", "1232", "7895"):
            self._gateway_error(504)
            return

        # Like Bugzilla's web filter: an empty 406. Bug 1238 rejects everything
        # but Updatebot's short replacement comment; bug 1239 rejects everything.
        if bug_id == "1239" or (bug_id == "1238" and "Bugzilla rejected it" not in content['comment']['body']):
            self.send_response(406)
            self.end_headers()
            return

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
            MockBugzillaServer.closed_bug_ids.append(int(bug_id))
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

    def testFileMissingComponent(self):
        library = Struct(**{
            'name': 'mylib',
            'bugzilla_product': 'Core',
            'bugzilla_component': 'Missing Component',
            'yaml_path': 'third_party/mylib/moz.yaml',
            'maintainer_bz': 'owner@example.com',
        })
        bug_id = self.bugzillaProvider.file_bug(library, "Update mylib to new version V1", "Details", [])
        self.assertEqual(bug_id, 457, "The bug should have been filed in Core :: General")

        filed = [b for b in MockBugzillaServer.filed_bugs if 'mylib' in b['summary']]
        self.assertEqual([(b['product'], b['component']) for b in filed],
                         [('Core', 'Missing Component'), ('Core', 'General'), ('Developer Infrastructure', 'Mach Vendor & Updatebot')])
        library_bug, followup = filed[1], filed[2]
        self.assertIn('cf_status_firefox88', library_bug)
        self.assertEqual(followup['blocks'], 457)
        self.assertEqual([f['requestee'] for f in followup['flags']], ['tom@mozilla.com', 'owner@example.com'])
        self.assertNotIn('cf_status_firefox88', followup)
        self.assertIn('third_party/mylib/moz.yaml', followup['description'])

    def testFileMissingComponentFollowUpFails(self):
        library = Struct(**{
            'name': 'broken',
            'bugzilla_product': 'Core',
            'bugzilla_component': 'Missing Component',
            'yaml_path': 'third_party/broken/moz.yaml',
            'maintainer_bz': 'owner@example.com',
        })
        # Failing to file the follow-up must not lose the library's bug.
        self.assertEqual(self.bugzillaProvider.file_bug(library, "Update broken to new version V1", "Details", []), 457)

    def testCommentRejected(self):
        os.environ['TASK_ID'] = 'abc123'
        try:
            self.bugzillaProvider.comment_on_bug(1238, "> ++ export VIRTUAL_ENV\n> ++ '[' -n /bin/bash ']'", needinfo='Jon')
        finally:
            del os.environ['TASK_ID']

        sent = MockBugzillaServer.received_comments["1238"]
        self.assertEqual(len(sent), 2, "Expected the rejected comment, then a replacement")
        self.assertIn("Bugzilla rejected it", sent[1]['comment']['body'])
        self.assertIn("https://firefox-ci-tc.services.mozilla.com/tasks/abc123", sent[1]['comment']['body'])
        self.assertEqual(sent[1]['flags'][0]['requestee'], 'Jon', "The replacement should keep the needinfo")

    def testVendorCommandsIncludeTheRevision(self):
        library = Struct(yaml_path="media/libfoo/moz.yaml")
        command = "./mach vendor media/libfoo/moz.yaml --revision 1.2.3"
        self.assertEqual(command, CommentTemplates.VENDOR_COMMAND(library, "1.2.3"))
        for comment in [
            CommentTemplates.DONE_BUILD_FAILURE(library, "1.2.3"),
            CommentTemplates.DONE_CLASSIFIED_FAILURE("", library, "1.2.3"),
            CommentTemplates.DONE_UNCLASSIFIED_FAILURE("", library, "1.2.3"),
            CommentTemplates.COULD_NOT_VENDOR(library, "1.2.3", "an error"),
            CommentTemplates.COULD_NOT_SUBMIT_DIFF_TOO_LARGE(library, "1.2.3", "too large"),
            CommentTemplates.COULD_NOT_VENDOR_ALL_FILES(library, "1.2.3", "an error"),
        ]:
            self.assertIn("`%s`" % command, comment)

    def _with_task_id(self, func):
        os.environ['TASK_ID'] = 'abc123'
        original_sleep = components.utilities.time.sleep
        components.utilities.time.sleep = lambda s: None
        try:
            return func()
        finally:
            components.utilities.time.sleep = original_sleep
            del os.environ['TASK_ID']

    def testCommentRetriedAfterGatewayError(self):
        self._with_task_id(lambda: self.bugzillaProvider.comment_on_bug(1230, "Retried comment"))
        self.assertEqual(len(MockBugzillaServer.received_comments["1230"]), 2)

    def testCommentNotRepeatedIfProcessed(self):
        # The comment failed with a 504 but Bugzilla posted it, so posting it again would duplicate it
        self._with_task_id(lambda: self.bugzillaProvider.comment_on_bug(1231, "Processed comment"))
        self.assertEqual(len(MockBugzillaServer.received_comments["1231"]), 1)

    def testCommentGatewayErrorGivesUp(self):
        with self.assertRaisesRegex(Exception, "status=504"):
            self._with_task_id(lambda: self.bugzillaProvider.comment_on_bug(1232, "Failing comment"))
        self.assertEqual(len(MockBugzillaServer.received_comments["1232"]), 3)

    def testFileRetriedAfterGatewayError(self):
        library = Struct(name='gw', bugzilla_product='Core', bugzilla_component='ImageLib')
        self.assertEqual(self._with_task_id(lambda: self.bugzillaProvider.file_bug(library, "Update gw to gateway-retry", "", [])), 459)
        self.assertEqual(len([b for b in MockBugzillaServer.filed_bugs if b['summary'] == "Update gw to gateway-retry"]), 2)

    def testFileNotRepeatedIfProcessed(self):
        library = Struct(name='gw', bugzilla_product='Core', bugzilla_component='ImageLib')
        self.assertEqual(self._with_task_id(lambda: self.bugzillaProvider.file_bug(library, "Update gw to gateway-processed", "", [])), 460)
        self.assertEqual(len([b for b in MockBugzillaServer.filed_bugs if b['summary'] == "Update gw to gateway-processed"]), 1)

    def testGatewayErrorWhileCheckingIsRetried(self):
        # The comment fails, then so does checking whether it was posted; the last
        # attempt checks again, finds it wasn't, and posts it
        self._with_task_id(lambda: self.bugzillaProvider.comment_on_bug(1233, "Retried comment"))
        self.assertEqual(MockBugzillaServer.comment_gets["1233"], 2)
        self.assertEqual(len(MockBugzillaServer.received_comments["1233"]), 2)

    def testCloseNotRepeatedIfProcessed(self):
        self._with_task_id(lambda: self.bugzillaProvider.wontfix_bug(7895, "Closing"))
        self.assertEqual(len(MockBugzillaServer.received_comments["7895"]), 1)

    def testCommentRejectedWithoutTaskId(self):
        self.assertIn("log of the Updatebot run", CommentTemplates.COMMENT_REJECTED(None))

    def testCommentAndReplacementRejected(self):
        with self.assertRaises(CommentRejectedError):
            self.bugzillaProvider.comment_on_bug(1239, "> ++ export VIRTUAL_ENV")
        self.assertEqual(len(MockBugzillaServer.received_comments["1239"]), 2, "Should give up after the replacement is rejected too")

    def testStatus(self):
        self.bugzillaProvider.mark_ff_version_affected(456, 76)

    def testGet(self):
        self.assertEqual({2: {'id': 2, "assigned_to_detail": {"id": 578488, "email": "tom@mozilla.com", "real_name": "Tom Ritter [:tjr]", "name": "tom@mozilla.com", "nick": "tjr"}, "assigned_to": "tom@mozilla.com"}}, self.bugzillaProvider.find_open_bugs_info([1, 2, 3]))

    def testClose(self):
        self.bugzillaProvider.wontfix_bug(7890, "Hello World")
        self.bugzillaProvider.dupe_bug(7891, "Hello Earth", 12345)
        self.assertIn(7891, MockBugzillaServer.closed_bug_ids)

    def testHasAutolandLink(self):
        self.assertTrue(self.bugzillaProvider.bug_has_landing_link(7892))
        self.assertTrue(self.bugzillaProvider.bug_has_landing_link(7893))
        self.assertTrue(self.bugzillaProvider.bug_has_landing_link(7894))
        self.assertFalse(self.bugzillaProvider.bug_has_landing_link(7891))


if __name__ == '__main__':
    unittest.main(verbosity=0)
