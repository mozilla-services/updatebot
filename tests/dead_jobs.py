#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.append(".")
sys.path.append("..")
import components.utilities
from apis.taskcluster import TaskclusterProvider, TryPushNotFoundError
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.logging import SimpleLogger, SimpleLoggerConfig
from components.utilities import Struct
from tasktypes.vendoring import VendorTaskRunner

HEAD = "a" * 40


class FakeDatabase:
    def __init__(self):
        self.updates = []

    def update_job_status(self, job, newstatus=None, newoutcome=None):
        self.updates.append((job.id, newstatus))
        job.status = newstatus or job.status


def runner(commands=None, outputs=None):
    r = VendorTaskRunner.__new__(VendorTaskRunner)
    r.logger = SimpleLogger()
    r.config = {'General': {'ff-version': 140}}
    r.dbProvider = FakeDatabase()
    if commands is not None:
        def run(args, clean_return=True, **kwargs):
            commands.append(args)
            return Struct(stdout=next((v for k, v in outputs.items() if k in " ".join(args)), ""), stderr="", returncode=0)
        r.cmdProvider = Struct(run=run)
    return r


def job(status, bug_open, age_days=30):
    return Struct(id=7, status=status, outcome=JOBOUTCOME.PENDING, bugzilla_is_open=bug_open, bugzilla_id=123,
                  created=datetime.now() - timedelta(days=age_days))


class TestDeadJobs(unittest.TestCase):
    def testObsoleteStatusWithClosedBugIsDone(self):
        for status in (JOBSTATUS.RELINQUISHED, JOBSTATUS.AWAITING_INITIAL_PLATFORM_TRY_RESULTS):
            r = runner()
            r._process_existing_job(None, None, job(status, bug_open=False))
            self.assertEqual(r.dbProvider.updates, [(7, JOBSTATUS.DONE)], status)

    def testObsoleteStatusWithOpenBugIsLeftAlone(self):
        r = runner()
        r._process_existing_job(None, None, job(JOBSTATUS.RELINQUISHED, bug_open=True))
        self.assertEqual(r.dbProvider.updates, [])

    def testOldTryRunWithoutResultsAndClosedBugIsDone(self):
        r = runner()
        self.assertFalse(r._job_is_completed_without_build_failures(None, job(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, bug_open=False), []))
        self.assertEqual(r.dbProvider.updates, [(7, JOBSTATUS.DONE)])

    def testTryRunWithoutResultsIsOtherwiseWaitedFor(self):
        for j in (job(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, bug_open=False, age_days=1),
                  job(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, bug_open=True)):
            r = runner()
            self.assertFalse(r._job_is_completed_without_build_failures(None, j, []))
            self.assertEqual(r.dbProvider.updates, [], "bug open: %s, created %s" % (j.bugzilla_is_open, j.created))

    def testTryPushTreeherderNoLongerHas(self):
        # Through the whole existing-job path, as Treeherder eventually deletes old pushes
        def missing_push(revision):
            raise TryPushNotFoundError("Treeherder has no push for try revision %s" % revision)

        for bug_open, expected in ((False, [(7, JOBSTATUS.DONE)]), (True, [])):
            r = runner()
            health_requests = []
            r.taskclusterProvider = Struct(get_job_details=missing_push, get_push_health=health_requests.append)
            j = job(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, bug_open=bug_open)
            j.try_runs = [Struct(revision="abcdef")]
            r._process_existing_job(None, None, j)
            self.assertEqual(r.dbProvider.updates, expected, "bug open: %s" % bug_open)
            self.assertEqual(health_requests, [], "Asked for the push health of a push that isn't there")

    def testCleanCheckoutIsNotReset(self):
        commands = []
        r = runner(commands, {"hg log": HEAD})
        with mock.patch.dict(os.environ, {"GECKO_HEAD_REV": HEAD}):
            r._reset_for_new_job()
        self.assertEqual([c[:2] for c in commands], [["hg", "status"], ["hg", "log"], ["hg", "--config"]])

    def testChangedCheckoutIsReset(self):
        for outputs in ({"hg status": "M some/file.c", "hg log": HEAD}, {"hg log": "b" * 40}):
            commands = []
            r = runner(commands, outputs)
            with mock.patch.dict(os.environ, {"GECKO_HEAD_REV": HEAD}):
                r._reset_for_new_job()
            self.assertIn(["hg", "checkout", "-C", "."], commands, outputs)
            self.assertIn(["hg", "update", HEAD], commands, outputs)


class TestMissingTryPush(unittest.TestCase):
    def _get_job_details(self, response):
        requests_made = []

        def get(url, **kwargs):
            requests_made.append(url)
            return Struct(ok=response[0], json=lambda: response[1], text=str(response[1]))
        provider = TaskclusterProvider({'url_treeherder': 'http://treeherder.invalid/', 'url_taskcluster': 'http://taskcluster.invalid/'})
        provider.update_config(dict(SimpleLoggerConfig, CommandProvider=Struct(run=None)))
        with mock.patch("apis.taskcluster.requests.get", get), \
                mock.patch.object(components.utilities, "RETRY_TIMES_OVERRIDE", 3), \
                mock.patch.object(components.utilities.time, "sleep", lambda s: None):
            try:
                provider.get_job_details("abcdef")
            except Exception as e:
                return e, len(requests_made)

    def testMissingPushIsNotRetried(self):
        e, requests_made = self._get_job_details((True, {"results": []}))
        self.assertIsInstance(e, TryPushNotFoundError)
        self.assertEqual(requests_made, 1)

    def testFailedRequestIsStillAnError(self):
        e, requests_made = self._get_job_details((False, {"detail": "Server Error"}))
        self.assertNotIsInstance(e, TryPushNotFoundError)
        self.assertEqual(requests_made, 3, "Expected a failed request to be retried")


if __name__ == '__main__':
    unittest.main(verbosity=0)
