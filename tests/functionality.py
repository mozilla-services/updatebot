#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import inspect
import unittest
import functools

from http import server
from threading import Thread

sys.path.append(".")
sys.path.append("..")
from automation import Updatebot

from components.utilities import Struct
from components.providerbase import BaseProvider
from components.logging import SimpleLoggingTest, LoggingProvider, log, logEntryExit
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.mach_vendor import VendorProvider
from components.hg import MercurialProvider
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

from tests.mock_commandprovider import TestCommandProvider
from tests.mock_treeherder_server import MockTreeherderServer
from tests.database import transform_db_config_to_tmp_db

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)


def TRY_OUTPUT(revision):
    return """
warning: 'mach try auto' is experimental, results may vary!
Test configuration changed. Regenerating backend.
Creating temporary commit for remote...
A try_task_config.json
pushing to ssh://hg.mozilla.org/try
searching for changes
remote: adding changesets
remote: adding manifests
remote: adding file changes
remote: recorded push in pushlog
remote: added 2 changesets with 1 changes to 6 files (+1 heads)
remote:
remote: View your changes here:
remote:   https://hg.mozilla.org/try/rev/a8adec7d117968b8f0006a9e54393dba7c444717
remote:   https://hg.mozilla.org/try/rev/%s
remote:
remote: Follow the progress of your build on Treeherder:
remote:   https://treeherder.mozilla.org/#/jobs?repo=try&revision=%s
remote: recorded changegroup in replication log in 0.011s
push complete
temporary commit removed, repository restored
""" % (revision, revision)


ARC_OUTPUT = """
Submitting 1 commit for review:
(New) 539627:dc5f73bea33e Bug 1652039 - Include checks in subdirectories in MozillaTidyModule.cpp r?andi
dc5f73bea33e is based off non-public commit 76fbb2477f01
Warning: found 2 untracked files (will not be submitted):
  sshkey.patch
  taskcluster/ci/fetch/toolchains.yml.orig
Automatically submitting (as per submit.auto_submit in ~/.moz-phab-config)

Creating new revision:
539627:dc5f73bea33e Bug 1652039 - Include checks in subdirectories in MozillaTidyModule.cpp r?andi
1 new orphan changesets
rebasing 539628:2f4625139f7e "Bug 1652037 - Wire up build_clang_tidy_external in build-clang.py r?#build" (civet)
1 files updated, 0 files merged, 0 files removed, 0 files unresolved
(activating bookmark civet)

Completed
(D83119) 539629:94adaadd8131 Bug 1652039 - Include checks in subdirectories in MozillaTidyModule.cpp r?andi
-> https://phabricator-dev.allizom.org/D83119
"""

CONDUIT_USERNAME_SEARCH_OUTPUT = """
{"error":null,"errorMessage":null,"response":{"data":[{"id":154,"type":"USER","phid":"PHID-USER-dd6rge2k2csia46r2wcw","fields":{"username":"tjr","realName":"Tom Ritter","roles":["verified","approved","activated"],"dateCreated":1519415695,"dateModified":1519416233,"policy":{"view":"public","edit":"no-one"}},"attachments":[]}],"maps":[],"query":{"queryKey":null},"cursor":{"limit":100,"after":null,"before":null,"order":null}}}
"""

CONDUIT_EDIT_OUTPUT = """
{"error":null,"errorMessage":null,"response":{"object":{"id":3643,"phid":"PHID-DREV-4pi6s6fwd57bktfzvfns"},"transactions":[{"phid":"PHID-XACT-DREV-om5mlg2ib34yaoi"},{"phid":"PHID-XACT-DREV-2pzq4qktezb7qqc"}]}}
"""


def DEFAULT_EXPECTED_VALUES(revision):
    return Struct(**{
        'library_version_id': "newversion_" + revision,
        'filed_bug_id': 50,
        'try_revision_id': revision,
        'phab_revision': 83119
    })


def COMMAND_MAPPINGS(expected_values):
    return {
        "./mach vendor": expected_values.library_version_id + " 2020-08-21T15:13:49.000+02:00",
        "./mach try auto": TRY_OUTPUT(expected_values.try_revision_id),
        "arc diff --verbatim": ARC_OUTPUT,
        "echo '{\"constraints\"": CONDUIT_USERNAME_SEARCH_OUTPUT,
        "echo '{\"transactions\":": CONDUIT_EDIT_OUTPUT
    }


class MockedBugzillaProvider(BaseProvider):
    def __init__(self, config):
        self._filed_bug_id = config['filed_bug_id']
        pass

    def file_bug(self, library, new_release_version, release_timestamp, see_also=None):
        return self._filed_bug_id

    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        pass


class TestFunctionality(SimpleLoggingTest):
    @classmethod
    def setUpClass(cls):
        cls.server = server.HTTPServer(('', 27490), MockTreeherderServer)
        t = Thread(target=cls.server.serve_forever)
        t.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    @staticmethod
    def _setup(try_revision, library_filter):
        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        configs = {
            'General': {'env': 'dev'},
            'Command': {'test_mappings': None},
            'Logging': localconfig['Logging'],
            'Database': db_config,
            'Vendor': {},
            'Bugzilla': {'filed_bug_id': None},
            'Mercurial': {},
            'Taskcluster': {
                'url_treeherder': 'http://localhost:27490/',
                'url_taskcluster': 'http://localhost:27490/',
            },
            'Phabricator': {},
        }

        providers = {
            # Not Mocked At All
            'Logging': LoggingProvider,
            # Fully Mocked
            'Command': TestCommandProvider,
            # Not Mocked At All
            'Database': DatabaseProvider,
            # Not Mocked At All
            'Vendor': VendorProvider,
            # Fully Mocked, avoids needing to make a fake
            # bugzilla server which provides no additional logic coverage
            'Bugzilla': MockedBugzillaProvider,
            # Not Mocked At All
            'Mercurial': MercurialProvider,
            # Not Mocked At All, but does point to a fake server
            'Taskcluster': TaskclusterProvider,
            # Not Mocked At All
            'Phabricator': PhabricatorProvider,
        }

        expected_values = DEFAULT_EXPECTED_VALUES(try_revision)
        configs['Bugzilla']['filed_bug_id'] = expected_values.filed_bug_id
        configs['Command']['test_mappings'] = COMMAND_MAPPINGS(expected_values)

        u = Updatebot(configs, providers)
        _check_jobs = functools.partial(TestFunctionality._check_jobs, u, library_filter, expected_values)

        # Ensure we don't have a dirty database with existing jobs
        tc = unittest.TestCase()
        for l in u.dbProvider.get_libraries():
            j = u.dbProvider.get_job(l, expected_values.library_version_id)
            tc.assertEqual(j, None, "When running %s, we found an existing job, indicating the database is dirty and should be cleaned." % inspect.stack()[1].function)

        return (u, expected_values, _check_jobs)

    @staticmethod
    def _cleanup(u, expected_values):
        for l in u.dbProvider.get_libraries():
            u.dbProvider.delete_job(l, expected_values.library_version_id)

    @staticmethod
    def _check_jobs(u, library_filter, expected_values, status, outcome):
        tc = unittest.TestCase()

        for l in u.dbProvider.get_libraries():
            if library_filter not in l.shortname:
                continue
            j = u.dbProvider.get_job(l, expected_values.library_version_id)

            tc.assertNotEqual(j, None)
            tc.assertEqual(l.shortname, j.library_shortname)
            tc.assertEqual(expected_values.library_version_id, j.version)
            tc.assertEqual(status, j.status)
            tc.assertEqual(outcome, j.outcome)
            tc.assertEqual(expected_values.filed_bug_id, j.bugzilla_id)
            tc.assertEqual(expected_values.phab_revision, j.phab_revision)
            tc.assertEqual(
                expected_values.try_revision_id, j.try_revision)

    @logEntryExit
    def testAllNewJobs(self):
        (u, expected_values, _check_jobs) = TestFunctionality._setup("try_rev", "")
        u.run()
        _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
        TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Jobs succeeded but there are classified failures
    @logEntryExit
    def testExistingJobClassifiedFailures(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup("e152bb86666565ee6619c15f60156cd6c79580a9", library_filter)

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs succeeded
            u.run(library_filter=library_filter)
            # Should be DONE
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.CLASSIFIED_FAILURES)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Build Failed
    @logEntryExit
    def testExistingJobBuildFailed(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup("55ca6286e3e4f4fba5d0448333fa99fc5a404a73", library_filter)

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it a build job failed
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.BUILD_FAILED)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> All Success
    @logEntryExit
    def testExistingJobAllSuccess(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup("56082fc4acfacba40993e47ef8302993c59e264e", library_filter)

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it a build job failed
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Same test on multiple platforms -> Unclassified Failure
    @logEntryExit
    def testExistingJobUnclassifiedFailureNoRetriggers(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup("4173dda99ea962d907e3fa043db5e26711085ed2", library_filter)

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it some tests failed, same test, multiple platforms
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Awaiting Retriggers -> Unclassified Failure
    @logEntryExit
    def testExistingJobUnclassifiedFailuresNeedingRetriggers(self):
        return
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup("ab2232a04301f1d2dbeea7050488f8ec2dde5451", library_filter)

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it a test failed
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.AWAITING_RETRIGGER_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it all the tests failed
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)
        finally:
            TestFunctionality._cleanup(u, expected_values)


if __name__ == '__main__':
    unittest.main()
