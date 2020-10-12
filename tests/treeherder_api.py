#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import json
import unittest

from http import server
from threading import Thread

sys.path.append(".")
sys.path.append("..")
from components.logging import SimpleLoggerConfig
from apis.taskcluster import TaskclusterProvider

from tests.mock_commandprovider import TestCommandProvider
from tests.mock_treeherder_server import MockTreeherderServer, FAILURE_CLASSIFICATIONS, EXPECTED_RETRIGGER_DECISION_TASK


class TestTaskclusterProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.HTTPServer(('', 27490), MockTreeherderServer)
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

    def test_job_details(self):
        job_list = self.taskclusterProvider.get_job_details('rev_good')
        self.assertEqual(len(job_list), 3737, "Did not receive the correct number of jobs from the server.")

    def test_push_health(self):
        push_health = self.taskclusterProvider.get_push_health("health_rev")
        self.assertEqual(len(push_health['metrics']['tests']['details']['needInvestigation']), 38, "Did not get expected number of needs-investigation tests")
        self.assertEqual(len(push_health['metrics']['tests']['details']['knownIssues']), 14, "Did not get expected number of known-issue tests")

    def test_correlation(self):
        job_list = self.taskclusterProvider.get_job_details('health_rev')
        push_health = self.taskclusterProvider.get_push_health("health_rev")

        results = self.taskclusterProvider.determine_jobs_to_retrigger(push_health, job_list)

        self.assertEqual(len(results['to_retrigger']), 21, "Did not get the expected number of jobs to retrigger.")

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
            'world'
        ]
        values = [
            ["HI", "EARTH"],
            ["WHAT", "UP"]
        ]
        data = self.taskclusterProvider._transform_job_list(properties, values)

        self.assertEqual(data[0].hello, "HI")
        self.assertEqual(data[0].world, "EARTH")

        self.assertEqual(data[1].hello, "WHAT")
        self.assertEqual(data[1].world, "UP")

    def test_retrigger(self):
        job_list = self.taskclusterProvider.get_job_details('rev_good')
        to_retrigger = [j for j in job_list if j.job_type_name == "source-test-mozlint-mingw-cap"]
        decision_task = self.taskclusterProvider.retrigger_jobs(job_list, to_retrigger)
        self.assertEqual(EXPECTED_RETRIGGER_DECISION_TASK, decision_task)


if __name__ == '__main__':
    unittest.main()
