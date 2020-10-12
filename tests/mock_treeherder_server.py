#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from http import server

from components.logging import log, LogLevel

FAILURE_CLASSIFICATIONS = """[{"id":7,"name":"autoclassified intermittent"},{"id":3,"name":"expected fail"},{"id":2,"name":"fixed by commit"},{"id":5,"name":"infra"},{"id":4,"name":"intermittent"},{"id":1,"name":"not classified"}]"""

EXPECTEDPATH_PUSH = "push/?revision="
EXPECTEDPATH_JOBS = "jobs/?push_id="
EXPECTEDPATH_FAILURECLASSIFICATION = "/failureclassification"
EXPECTEDPATH_ACTIONSJSON = "api/queue/v1/task"
EXPECTEDPATH_RETRIGGER = "api/hooks/v1/hooks"
EXPECTEDPATH_PUSHHEALTH = "api/push/health/?revision="

TRY_REVISIONS = {
    'rev_broken': "{\"results\":[{\"missing_id\":0}]}",
    'rev_good': "{\"results\":[{\"id\":1}]}",
    'e152bb86666565ee6619c15f60156cd6c79580a9': "{\"results\":[{\"id\":2}]}",
    '55ca6286e3e4f4fba5d0448333fa99fc5a404a73': "{\"results\":[{\"id\":3}]}",
    '56082fc4acfacba40993e47ef8302993c59e264e': "{\"results\":[{\"id\":4}]}",
    'ab2232a04301f1d2dbeea7050488f8ec2dde5451': "{\"results\":[{\"id\":5}]}",
    'health_rev': "{\"results\":[{\"id\":6}]}",
}

HEALTH_REVISIONS = {
    "health_rev": "treeherder_api_response_pushhealth_health.txt"
}

PUSH_IDS = {
    # The keys are _x_y_z meaning:
    #  x: push_id. from above in TRY_REVISIONS
    #  y: the page. Unless a result is multi_page it will just be 1
    #  x: request number. The first time a document is requested, this will be 1, the second time, 2, etc
    #     specify 'A' to indicate this response should be used for all requests
    # rev_broken/good
    '1_1_A': "treeherder_api_response_1.txt",
    '1_2_A': "treeherder_api_response_2.txt",
    # testExistingJobSucceeded
    '2_1_1': "treeherder_api_response_jobs_still_running.txt",
    '2_1_2': "treeherder_api_response_all_succeeded.txt",
    # testExistingJobBuildFailed
    '3_1_1': "treeherder_api_response_jobs_still_running.txt",
    '3_1_2': "treeherder_api_response_build_failed.txt",
    # testExistingJobClassifiedFailure
    '4_1_1': "treeherder_api_response_jobs_still_running.txt",
    '4_1_2': "treeherder_api_response_classified_failure.txt",
    # testExistingJobUnclassifiedFailure
    '5_1_1': "treeherder_api_response_jobs_still_running.txt",
    '5_1_2': "treeherder_api_response_jobs_one_unclassified_failure.txt",
    '5_1_3': "treeherder_api_response_jobs_unclassified_failure_retriggers_done.txt",
    # push_health stuff
    '6_1_A': "treeherder_api_response_pushhealth_jobdetails.txt",

}

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

seen_counters = {}


def find_and_increment_seen_counter(key):
    if key not in seen_counters:
        seen_counters[key] = 1
    else:
        seen_counters[key] += 1
    return str(seen_counters[key])


def get_appropriate_filename(path):
    has_page = "&page=" in path
    i1 = path.index(EXPECTEDPATH_JOBS) + len(EXPECTEDPATH_JOBS)
    i2 = path.index("&page=") if has_page else len(path)
    push_id = path[i1:i2]

    page = path[path.index("&page=") + len("&page="):] if has_page else "1"

    key = push_id + "_" + page
    seen_counter = find_and_increment_seen_counter(key)
    key += "_" + seen_counter

    log("Checking for push_id", push_id, "page", page, "seen", seen_counter, level=LogLevel.Debug)

    if key not in PUSH_IDS:
        key = push_id + "_" + page + "_" + "A"
        print("Response-specific key missing, checking for key ", key)
        if key not in PUSH_IDS:
            assert False, "Could not find either key in PUSH_IDS"

    return PUSH_IDS[key]


class MockTreeherderServer(server.BaseHTTPRequestHandler):
    def do_POST(self):
        if EXPECTEDPATH_RETRIGGER in self.path:
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

        if EXPECTEDPATH_PUSH in self.path:
            revision = self.path[self.path.index(EXPECTEDPATH_PUSH) + len(EXPECTEDPATH_PUSH):]
            log("MockTreeherderServer (push): Looking for revision %s" % revision, level=LogLevel.Info)

            if revision not in TRY_REVISIONS:
                assert False, "MockTreeherderServer: Could not find that revision"

            self.wfile.write(TRY_REVISIONS[revision].encode())
            return

        elif EXPECTEDPATH_FAILURECLASSIFICATION in self.path:
            self.wfile.write(FAILURE_CLASSIFICATIONS.encode())
            return

        elif EXPECTEDPATH_PUSHHEALTH in self.path:
            revision = self.path[self.path.index(EXPECTEDPATH_PUSHHEALTH) + len(EXPECTEDPATH_PUSHHEALTH):]
            log("MockTreeherderServer (push health): Looking for revision %s" % revision, level=LogLevel.Info)

            if revision not in HEALTH_REVISIONS:
                assert False, "MockTreeherderServer: Could not find that revision"

            filename = HEALTH_REVISIONS[revision]

        else:
            if EXPECTEDPATH_JOBS in self.path:
                filename = get_appropriate_filename(self.path)
            elif EXPECTEDPATH_ACTIONSJSON in self.path:
                filename = "taskcluster_api_response_actionsjson.txt"
            else:
                assert False, "MockTreeherderServer GET got a path it didn't expect: " + self.path

        log("MockTreeherderServer: Streaming %s" % filename, level=LogLevel.Info)

        with open(file_prefix + filename, "rb") as f:
            for line in f:
                self.wfile.write(line)
