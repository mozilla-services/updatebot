#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import json
import unittest
import requests

from http import server
from threading import Thread

sys.path.append(".")
sys.path.append("..")
from components.logging import SimpleLoggerConfig
from components.utilities import static_vars, Struct
import components.utilities
from apis.taskcluster import TaskclusterProvider

from tests.functionality_utilities import treeherder_response
from tests.mock_commandprovider import TestCommandProvider
from tests.mock_treeherder_server import MockTreeherderServerFactory, FAILURE_CLASSIFICATIONS, EXPECTED_RETRIGGER_DECISION_TASK, TYPE_HEALTH


# Because jobs_count won't be consistent because we call this function for all tests
#  use a separate boolean for the paging test. We flip it back and forth because
#  we return the paged data in two different tests
@static_vars(have_sent_page_1=False)
@treeherder_response
def treeherder_responses(requesttype, fullpath):
    if "/bug_suggestions/" in fullpath:
        if "/604934614/" in fullpath:
            return "bugsuggestions_build_intermittent.txt"
        if "/503/" in fullpath:
            return 503
        return "bugsuggestions_build_failure.txt"

    if "push_id=1" in fullpath:
        if treeherder_responses.have_sent_page_1:
            treeherder_responses.have_sent_page_1 = False
            return "jobs_paged_2.txt"
        else:
            treeherder_responses.have_sent_page_1 = True
            return "jobs_paged_1.txt"

    if "health_rev" in fullpath:
        if requesttype == TYPE_HEALTH:
            return "health_correlation_example.txt"
        else:
            return "jobs_correlation_example.txt"
    return ""


class TestTaskclusterProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.HTTPServer(('', 27490), MockTreeherderServerFactory(treeherder_responses))
        cls.commandProvider = TestCommandProvider({})
        cls.commandProvider.update_config(SimpleLoggerConfig)

        cls.taskclusterProvider = TaskclusterProvider({
            'url_treeherder': 'http://localhost:27490/',
            'url_taskcluster': 'http://localhost:27490/',
        })
        additional_config = SimpleLoggerConfig
        additional_config.update({'CommandProvider': cls.commandProvider})
        cls.taskclusterProvider.update_config(additional_config)

        t = Thread(target=cls.server.serve_forever)
        t.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_failure_classification(self):
        f = self.taskclusterProvider.failure_classifications
        j = json.loads(FAILURE_CLASSIFICATIONS)
        self.assertEqual(j[0]['name'], f[7])

    def test_push_exception_handling(self):
        try:
            self.taskclusterProvider.get_job_details('rev_broken')
        except Exception:
            self.assertTrue(True, "Did not see an exception that we expected.")
        else:
            self.assertTrue(False, "Expected an exception from taskclusterProvider but didn't see it.")

    def test_job_details_paged(self):
        # Job paging relies on using the ID of the push which is in the json, so with the new server we need to use the id that's in the json
        job_list = self.taskclusterProvider.get_job_details('1')
        self.assertEqual(len(job_list), 3737, "Did not receive the correct number of jobs from the server.")

    def test_push_health(self):
        push_health = self.taskclusterProvider.get_push_health("health_rev")
        self.assertEqual(len(push_health['metrics']['tests']['details']['needInvestigation']), 38, "Did not get expected number of needs-investigation tests")
        self.assertEqual(len(push_health['metrics']['tests']['details']['knownIssues']), 14, "Did not get expected number of known-issue tests")

    def test_correlation(self):
        job_list = self.taskclusterProvider.get_job_details('health_rev')
        push_health = self.taskclusterProvider.get_push_health("health_rev")

        results = self.taskclusterProvider.determine_jobs_to_retrigger(push_health, job_list)

        self.assertEqual(len(results['to_retrigger']), 26, "Did not get the expected number of jobs to retrigger.")

        return  # Debugging code below
        print("Known Issues:")
        for t in results['known_issues']:
            print("\t", t)
            for j in results['known_issues'][t]:
                print("\t\t-", j.job_type_name)

        print("Needs Investigation:")
        for t in results['to_investigate']:
            print("\t", t)
            for j in results['to_investigate'][t]:
                print("\t\t-", j.job_type_name)

        print("To Retrigger (%s):" % len(results['to_retrigger']))
        for j in results['to_retrigger']:
            print("\t-", j.job_type_name)

    def test_transform(self):
        properties = [
            'hello',
            'world',
            'job_type_name'
        ]
        values = [
            ["HI", "EARTH", "Win Build"],
            ["WHAT", "UP", "Gecko Decision Task"]
        ]
        data = self.taskclusterProvider._transform_job_list(properties, values)

        self.assertEqual(data[0].hello, "HI")
        self.assertEqual(data[0].world, "EARTH")
        self.assertEqual(data[0].decision_task.hello, "WHAT")

        self.assertEqual(data[1].hello, "WHAT")
        self.assertEqual(data[1].world, "UP")
        self.assertEqual(data[1].decision_task.hello, "WHAT")

    def test_known_intermittent(self):
        # The xul.lib install race from bug 2089270's try run, which matches bug 2087899
        job = Struct(id=604934614, job_type_name="build-win64/opt", task_id="ZBU6hYOhTiyVUWlkodykhw")
        self.assertTrue(self.taskclusterProvider.is_known_intermittent(job))

    def test_not_known_intermittent(self):
        # A compile error, followed by generic lines that match intermittent bugs without ids
        # and a Perma bug
        job = Struct(id=111, job_type_name="build-linux64/opt", task_id="AAAAAAAAAAAAAAAAAAAAAA")
        self.assertFalse(self.taskclusterProvider.is_known_intermittent(job))

    def test_bug_suggestions_http_error(self):
        # Treeherder's errors have JSON bodies, which must be retried and then raised rather
        # than parsed as bug suggestions
        calls = treeherder_responses.bug_suggestions_calls
        job = Struct(id=503, job_type_name="build-linux64/opt", task_id="AAAAAAAAAAAAAAAAAAAAAA")
        original_override, original_sleep = components.utilities.RETRY_TIMES_OVERRIDE, components.utilities.time.sleep
        components.utilities.RETRY_TIMES_OVERRIDE = 3
        components.utilities.time.sleep = lambda s: None
        try:
            with self.assertRaises(requests.exceptions.HTTPError):
                self.taskclusterProvider.is_known_intermittent(job)
        finally:
            components.utilities.RETRY_TIMES_OVERRIDE, components.utilities.time.sleep = original_override, original_sleep
        self.assertEqual(treeherder_responses.bug_suggestions_calls - calls, 3, "Expected the request to be retried")

    def test_build_components_not_checked_for_intermittents(self):
        # build-components-* jobs run unit tests, so don't treat their failures as build
        # intermittents, even if the first line matches one
        calls = treeherder_responses.bug_suggestions_calls
        job = Struct(id=604934614, job_type_name="build-components-feature-qr", task_id="ZBU6hYOhTiyVUWlkodykhw")
        self.assertFalse(self.taskclusterProvider.is_known_intermittent(job))
        self.assertEqual(treeherder_responses.bug_suggestions_calls, calls, "Should not have requested bug suggestions")

    def test_retrigger(self):
        job_list = self.taskclusterProvider.get_job_details('1')
        to_retrigger = [j for j in job_list if j.job_type_name == "source-test-mozlint-mingw-cap"]
        decision_tasks = self.taskclusterProvider.retrigger_jobs(to_retrigger)
        self.assertEqual(EXPECTED_RETRIGGER_DECISION_TASK, decision_tasks[0])


if __name__ == '__main__':
    unittest.main(verbosity=0)
