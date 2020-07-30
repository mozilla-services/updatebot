#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from http import server

FAILURE_CLASSIFICATIONS = """[{"id":7,"name":"autoclassified intermittent"},{"id":3,"name":"expected fail"},{"id":2,"name":"fixed by commit"},{"id":5,"name":"infra"},{"id":4,"name":"intermittent"},{"id":1,"name":"not classified"}]"""

EXPECTEDPATH_PUSH = "push/?revision="
EXPECTEDPATH_JOBS = "jobs/?push_id="
EXPECTEDPATH_FAILURECLASSIFICATION = "/failureclassification"
EXPECTEDPATH_ACTIONSJSON = "api/queue/v1/task"

TRY_REVISIONS = {
    'rev_broken': "{\"results\":[{\"missing_id\":0}]}",
    'rev_good': "{\"results\":[{\"id\":1}]}",
}

PUSH_IDS = {
    '1_1' : "treeherder_api_response_1.txt",
    '1_2' : "treeherder_api_response_2.txt",
}

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
    print("Chcking for push_id", push_id, "page", page)

    key = push_id + "_" + page

    if key not in PUSH_IDS:
        assert False, "Could not find the key " + key + " in PUSH_IDS"

    return PUSH_IDS[key]


class MockTreeherderServer(server.BaseHTTPRequestHandler):
    def do_GET(self):

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        if EXPECTEDPATH_PUSH in self.path:
            revision = self.path[self.path.index(EXPECTEDPATH_PUSH) + len(EXPECTEDPATH_PUSH):]
            print("MockTreeherderServer: Looking for revision %s" % revision)

            if revision not in TRY_REVISIONS:
                assert False, "MockTreeherderServer: Could not find that revision"

            self.wfile.write(TRY_REVISIONS[revision].encode())

        elif EXPECTEDPATH_FAILURECLASSIFICATION in self.path:
            self.wfile.write(FAILURE_CLASSIFICATIONS.encode())

        else:
            prefix = "tests/" if not os.getcwd().endswith("tests") else ""
            if EXPECTEDPATH_JOBS in self.path:
                filename = get_appropriate_filename(self.path)
            elif EXPECTEDPATH_ACTIONSJSON in self.path:
                filename = "taskcluster_api_response_actionsjson.txt"
            else:
                assert False, "MockTreeherderServer got a path it didn't expect"

            print("MockTreeherderServer: Streaming %s" % filename)

            with open(prefix + filename, "rb") as f:
                for line in f:
                    self.wfile.write(line)
