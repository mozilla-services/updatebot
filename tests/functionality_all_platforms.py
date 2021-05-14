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
from components.scmprovider import SCMProvider
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

from tests.mock_commandprovider import TestCommandProvider
from tests.mock_libraryprovider import MockLibraryProvider
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

GIT_PRETTY_OUTPUT = """
c8011782e13d5c1c402b07b7a02efa2f8d400efa|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000
f9e59ad078552424ca165644f4da3b4e2687c3dc|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000
62c10c170bb33f1ad6c9eb13d0cbdf13f95fb27e|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000
"""

GIT_DIFF_FILES_CHANGES = """
M	src/libANGLE/renderer/vulkan/VertexArrayVk.cpp
M	src/tests/gl_tests/StateChangeTest1.cpp
A	src/tests/gl_tests/StateChangeTest2.cpp
D	src/tests/gl_tests/StateChangeTest3.cpp
R	src/tests/gl_tests/StateChangeTest4.cpp
Q	src/tests/gl_tests/StateChangeTest5.cpp
"""

GIT_COMMIT_BODY = """
If glBufferSubData results in a new vk::BufferHelper allocation,
VertexArrayVk::mCurrentElementArrayBuffer needs to be updated.
VertexArrayVk::syncState was working under the assumption that
DIRTY_BIT_ELEMENT_ARRAY_BUFFER_DATA cannot result in a vk::BufferHelper
pointer change.

This assumption was broken in
https://chromium-review.googlesource.com/c/angle/angle/+/2204655.

Bug: b/178231226
Change-Id: I969549c5ffec3456bdc08ac3e03a0fa0e7b4593f
(cherry picked from commit bb062070cb5257098f0e2d775fa66b74d6d32468)
Reviewed-on: https://chromium-review.googlesource.com/c/angle/angle/+/2693346
Reviewed-by: Jamie Madill <jmadill@chromium.org>
Commit-Queue: Jamie Madill <jmadill@chromium.org>
"""


def DEFAULT_EXPECTED_VALUES(sha_hash, get_filed_bug_id_func):
    # This is a bit confusing; but we use the same SHA hash for the current, and new
    # library revision (which doesn't mattter, Updatebot doesn't compare versions on
    # Vendoring tasks, it just believes an updated is needed if ./mach vendor --check-for-update
    # says so) and _also_ the revision id returned from 'the try server'.  We suffix
    # the library hashes with _current and _new, but the try revision hash is left unchanged
    return Struct(**{
        'library_new_version_id': sha_hash + "_new",
        'try_revision_id': sha_hash,
        'get_filed_bug_id_func': get_filed_bug_id_func,
        'phab_revision': 83119
    })


def COMMAND_MAPPINGS(expected_values):
    return {
        "./mach vendor": lambda :expected_values.library_new_version_id + " 2020-08-21T15:13:49.000+02:00",
        "./mach try auto": lambda :TRY_OUTPUT(expected_values.try_revision_id),
        "hg commit": lambda :"",
        "hg checkout -C .": lambda :"",
        "hg purge .": lambda :"",
        "hg status": lambda :"",
        "hg strip": lambda :"",
        "arc diff --verbatim": lambda :ARC_OUTPUT,
        "echo '{\"constraints\"": lambda :CONDUIT_USERNAME_SEARCH_OUTPUT,
        "echo '{\"transactions\":": lambda :CONDUIT_EDIT_OUTPUT,
        "git log -1 --oneline": lambda :"0481f1c (HEAD -> issue-115-add-revision-to-log, origin/issue-115-add-revision-to-log) Issue #115 - Add revision of updatebot to log output",
        "git clone https://example.invalid .": lambda :"",
        "git rev-parse --abbrev-ref HEAD": lambda :"master",
        "git branch --contains": lambda :"master",
        "git log --pretty=%H|%ai|%ci": lambda :GIT_PRETTY_OUTPUT,
        "git diff --name-status": lambda :GIT_DIFF_FILES_CHANGES,
        "git log --pretty=%s": lambda :"Roll SPIRV-Tools from a61d07a72763 to 1cda495274bb (1 revision)",
        "git log --pretty=%an": lambda :"Tom Ritter",
        "git log --pretty=%b": lambda :GIT_COMMIT_BODY,
    }


ALL_BUGS = False
ONLY_OPEN = True


class MockedBugzillaProvider(BaseProvider):
    def __init__(self, config):
        self.config = config
        self._get_filed_bug_id_func = config['get_filed_bug_id_func']
        self._filed_bug_ids_func = config['filed_bug_ids_func']
        if config['assert_affected_func']:
            self._assert_affected_func = config['assert_affected_func']
        else:
            self._assert_affected_func = lambda a, b, c: True

    def file_bug(self, library, summary, description, cc, needinfo, see_also=None):
        return self._get_filed_bug_id_func()

    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        pass

    def wontfix_bug(self, bug_id, comment):
        pass

    def dupe_bug(self, bug_id, comment, dupe_id):
        pass

    def find_open_bugs(self, bug_ids):
        return self._filed_bug_ids_func(ONLY_OPEN)

    def mark_ff_version_affected(self, bug_id, ff_version, affected):
        self._assert_affected_func(bug_id, ff_version, affected)


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
    def _setup(sha_hash,
               library_filter,
               get_filed_bug_id_func,
               filed_bug_ids_func,
               assert_affected_func=None,
               keep_tmp_db=False):
        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        db_config['keep_tmp_db'] = keep_tmp_db

        configs = {
            'General': {
                'env': 'dev',
                'gecko-path': '.',
                'ff-version': '87',
                'repo': 'https://hg.mozilla.org/mozilla-central'
            },
            'Command': {'test_mappings': None},
            'Logging': localconfig['Logging'],
            'Database': db_config,
            'Vendor': {},
            'Bugzilla': {
                'get_filed_bug_id_func': get_filed_bug_id_func,
                'filed_bug_ids_func': filed_bug_ids_func,
                'assert_affected_func': assert_affected_func
            },
            'Mercurial': {},
            'Taskcluster': {
                'url_treeherder': 'http://localhost:27490/',
                'url_taskcluster': 'http://localhost:27490/',
            },
            'Phabricator': {},
            'Library': {
                'vendoring_revision_override': sha_hash + "_current",
            }
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
            # Fully Mocked
            'Library': MockLibraryProvider,
            # Fully Mocked, avoids needing to make a fake
            # bugzilla server which provides no additional logic coverage
            'Bugzilla': MockedBugzillaProvider,
            # Not Mocked At All
            'Mercurial': MercurialProvider,
            # Not Mocked At All, but does point to a fake server
            'Taskcluster': TaskclusterProvider,
            # Not Mocked At All
            'Phabricator': PhabricatorProvider,
            'SCM': SCMProvider,
        }

        expected_values = DEFAULT_EXPECTED_VALUES(sha_hash, get_filed_bug_id_func)
        configs['Command']['test_mappings'] = COMMAND_MAPPINGS(expected_values)

        u = Updatebot(configs, providers)
        _check_jobs = functools.partial(TestFunctionality._check_jobs, u, library_filter, expected_values)

        # Ensure we don't have a dirty database with existing jobs
        tc = unittest.TestCase()
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            for task in lib.tasks:
                if task.type != 'vendoring':
                    continue
                j = u.dbProvider.get_job(lib, expected_values.library_new_version_id)
                tc.assertEqual(j, None, "When running %s, we found an existing job, indicating the database is dirty and should be cleaned." % inspect.stack()[1].function)

        return (u, expected_values, _check_jobs)

    @staticmethod
    def _cleanup(u, expected_values):
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            for task in lib.tasks:
                if task.type != 'vendoring':
                    continue
                u.dbProvider.delete_job(library=lib, version=expected_values.library_new_version_id)

    @staticmethod
    def _check_jobs(u, library_filter, expected_values, status, outcome):
        tc = unittest.TestCase()

        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            if library_filter not in lib.name:
                continue

            for task in lib.tasks:
                if task.type != 'vendoring':
                    continue

                j = u.dbProvider.get_job(lib, expected_values.library_new_version_id)

                tc.assertNotEqual(j, None)
                tc.assertEqual(lib.name, j.library_shortname)
                tc.assertEqual(expected_values.library_new_version_id, j.version)
                tc.assertEqual(status, j.status, "Expected status %s, got status %s" % (status.name, j.status.name))
                tc.assertEqual(outcome, j.outcome, "Expected outcome %s, got outcome %s" % (outcome.name, j.outcome.name))
                tc.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)
                tc.assertEqual(expected_values.phab_revision, j.phab_revision)
                tc.assertEqual(len(j.try_runs), 1)
                tc.assertEqual(
                    expected_values.try_revision_id, j.try_runs[0].revision)
                tc.assertEqual('all platforms', j.try_runs[0].purpose)

    @logEntryExit
    def testAllNewJobs(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            "try_rev",
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )
        u.run(library_filter=library_filter)
        _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
        TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Jobs succeeded but there are classified failures
    @logEntryExit
    def testExistingJobClassifiedFailures(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            "e152bb86666565ee6619c15f60156cd6c79580a9",
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
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
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            "55ca6286e3e4f4fba5d0448333fa99fc5a404a73",
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
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
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            "56082fc4acfacba40993e47ef8302993c59e264e",
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it a build job failed
            u.run(library_filter=library_filter)
            # Should be DONE and Success.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Same test on multiple platforms -> Unclassified Failure
    @logEntryExit
    def testExistingJobUnclassifiedFailureNoRetriggers(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            "4173dda99ea962d907e3fa043db5e26711085ed2",
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it some tests failed, same test, multiple platforms
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Awaiting Retriggers -> Unclassified Failure
    @logEntryExit
    def testExistingJobUnclassifiedFailuresNeedingRetriggers(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            "ab2232a04301f1d2dbeea7050488f8ec2dde5451",
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
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
    unittest.main(verbosity=0)
