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
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.logging import SimpleLogger
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


if __name__ == '__main__':
    unittest.main(verbosity=0)
