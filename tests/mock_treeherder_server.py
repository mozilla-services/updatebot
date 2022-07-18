#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from http import server

from components.logging import log, LogLevel

TYPE_HEALTH = "health"
TYPE_JOBS = "jobs"

FAILURE_CLASSIFICATIONS = """[{"id":7,"name":"autoclassified intermittent"},{"id":3,"name":"expected fail"},{"id":2,"name":"fixed by commit"},{"id":5,"name":"infra"},{"id":4,"name":"intermittent"},{"id":1,"name":"not classified"}]"""

EXPECTEDPATH_PUSH = "push/?revision="
EXPECTEDPATH_JOBS = "jobs/?push_id="
EXPECTEDPATH_FAILURECLASSIFICATION = "/failureclassification"
EXPECTEDPATH_ACTIONSJSON = "api/queue/v1/task"
EXPECTEDPATH_RETRIGGER = "api/hooks/v1/hooks"
EXPECTEDPATH_PUSHHEALTH = "push/health/?revision="

EXPECTED_RETRIGGER_DECISION_TASK = "CQNj9DM5Qn2-rDY4fTxgSQ"
RETRIGGER_RESPONSE = """
{
  "status": {
    "taskId": "%s",
    "provisionerId": "gecko-3",
    "workerType": "decision",
    "schedulerId": "gecko-level-3",
    "taskGroupId": "Igy-K0sYSlKnWt4i4nM_8g",
    "deadline": "2020-07-31T19:09:46.398Z",
    "expires": "2021-07-30T19:09:46.398Z",
    "retriesLeft": 5,
    "state": "pending",
    "runs": [
      {
        "runId": 0,
        "state": "pending",
        "reasonCreated": "scheduled",
        "scheduled": "2020-07-30T19:09:46.441Z"
      }
    ]
  }
}
""" % EXPECTED_RETRIGGER_DECISION_TASK


def MockTreeherderServerFactory(response_function):
    class MockTreeherderServer(server.BaseHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.response_func = response_function
            super(MockTreeherderServer, self).__init__(*args, **kwargs)

        def do_POST(self):
            if EXPECTEDPATH_RETRIGGER in self.path:
                log("MockTreeherderServer (retrigger): streaming standard retrigger response", level=LogLevel.Info)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(RETRIGGER_RESPONSE.encode())
            else:
                assert False, "MockTreeherderServer POST got a path it didn't expect: " + self.path

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            file_prefix = "tests/" if not os.getcwd().endswith("tests") else ""
            file_prefix += "treeherder_api_responses/"

            if EXPECTEDPATH_PUSH in self.path:
                revision = self.path[self.path.index(EXPECTEDPATH_PUSH) + len(EXPECTEDPATH_PUSH):]
                log("MockTreeherderServer (push): Looking for revision %s" % revision, level=LogLevel.Info)

                # Ordinarily the push id is an integer, but here we'll just kick the try revision
                # back and use that as the ID.
                self.wfile.write(("{\"results\":[{\"id\": \"%s\"}]}" % revision).encode())
                return

            elif EXPECTEDPATH_FAILURECLASSIFICATION in self.path:
                self.wfile.write(FAILURE_CLASSIFICATIONS.encode())
                return

            elif EXPECTEDPATH_PUSHHEALTH in self.path:
                revision = self.path[self.path.index(EXPECTEDPATH_PUSHHEALTH) + len(EXPECTEDPATH_PUSHHEALTH):]
                log("MockTreeherderServer (push health): Looking for revision %s" % revision, level=LogLevel.Info)
                filename = self.response_func(TYPE_HEALTH, revision)

            else:
                if EXPECTEDPATH_ACTIONSJSON in self.path:
                    log("MockTreeherderServer (actiosnjson)", level=LogLevel.Info)
                    filename = "actionsjson.txt"
                elif EXPECTEDPATH_JOBS in self.path:
                    log("MockTreeherderServer (jobs): Got path %s" % self.path, level=LogLevel.Info)
                    filename = self.response_func(TYPE_JOBS, self.path)
                else:
                    assert False, "MockTreeherderServer GET got a path it didn't expect: " + self.path

            assert filename, "MockTreeherderServer somehow got a blank filename"
            log("MockTreeherderServer: Streaming %s" % filename, level=LogLevel.Info)

            with open(file_prefix + filename, "rb") as f:
                for line in f:
                    self.wfile.write(line)
    return MockTreeherderServer
