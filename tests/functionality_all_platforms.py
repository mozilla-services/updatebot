#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import copy
import inspect
import unittest
import itertools
import functools

from http import server
from threading import Thread

sys.path.append(".")
sys.path.append("..")
from automation import Updatebot

from components.utilities import Struct, raise_
from components.providerbase import BaseProvider
from components.logging import SimpleLoggingTest, LoggingProvider, log, logEntryExit
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.mach_vendor import VendorProvider
from components.hg import MercurialProvider
from components.scmprovider import SCMProvider
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

from tests.functionality_utilities import AssertFalse, SHARED_COMMAND_MAPPINGS, TRY_OUTPUT, CONDUIT_EDIT_OUTPUT
from tests.mock_commandprovider import TestCommandProvider
from tests.mock_libraryprovider import MockLibraryProvider
from tests.mock_treeherder_server import MockTreeherderServer, reset_seen_counters
from tests.database import transform_db_config_to_tmp_db

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)


def DEFAULT_EXPECTED_VALUES(git_pretty_output_func, get_filed_bug_id_func):
    return Struct(**{
        'git_pretty_output_func': git_pretty_output_func,
        'library_new_version_id': lambda: git_pretty_output_func(False)[0].split("|")[0],
        'try_revision_id': lambda: git_pretty_output_func(False)[0].split("|")[0],
        'get_filed_bug_id_func': get_filed_bug_id_func,
        'phab_revision_func': lambda: 83000 + get_filed_bug_id_func()
    })


def COMMAND_MAPPINGS(expected_values, callbacks):
    ret = SHARED_COMMAND_MAPPINGS(expected_values, callbacks)
    ret.update({
        "./mach try auto": callbacks['try_submit'] if 'try_submit' in callbacks else lambda: TRY_OUTPUT(expected_values.try_revision_id()),
        "./mach try fuzzy": callbacks['try_submit'] if 'try_submit' in callbacks else lambda: TRY_OUTPUT(expected_values.try_revision_id(), False),
    })
    return ret


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
            self._assert_affected_func = AssertFalse

    def file_bug(self, library, summary, description, cc, needinfo=None, see_also=None):
        references_prior_bug = "I've never filed a bug on before." in description
        if len(self._filed_bug_ids_func(False)) > 0:
            assert references_prior_bug, "We did not reference a prior bug when we should have"
            self.config['expect_a_dupe'] = True
        else:
            assert not references_prior_bug, "We should not have referenced a prior bug but we did"
            self.config['expect_a_dupe'] = False

        return self._get_filed_bug_id_func()

    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        pass

    def wontfix_bug(self, bug_id, comment):
        pass

    def dupe_bug(self, bug_id, comment, dup_id):
        assert self.config['expect_a_dupe'], "We marked a bug as a duplicate when we weren't execting to."
        assert bug_id == self._filed_bug_ids_func(ALL_BUGS)[-1], \
            "We expected to close %s as a dupe, but it was actually %s" % (
                self._filed_bug_ids_func(ALL_BUGS)[-1], bug_id)
        assert dup_id == self._get_filed_bug_id_func(), \
            "We expected to mark %s as a dupe of %s as a dupe, but we actually marked it a dupe of %s" % (
                bug_id, self._get_filed_bug_id_func(), dup_id)

    def find_open_bugs(self, bug_ids):
        return self._filed_bug_ids_func(ONLY_OPEN)

    def mark_ff_version_affected(self, bug_id, ff_version, affected):
        self._assert_affected_func(bug_id, ff_version, affected)


PROVIDERS = {
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
    def _setup(git_pretty_output_func,
               library_filter,
               get_filed_bug_id_func,
               filed_bug_ids_func,
               assert_affected_func=None,
               callbacks={},
               keep_tmp_db=False):
        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        db_config['keep_tmp_db'] = keep_tmp_db

        configs = {
            'General': {
                'env': 'dev',
                'gecko-path': '.',
                'ff-version': 87,
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
                'vendoring_revision_override': "_current",
            }
        }

        expected_values = DEFAULT_EXPECTED_VALUES(git_pretty_output_func, get_filed_bug_id_func)
        configs['Command']['test_mappings'] = COMMAND_MAPPINGS(expected_values, callbacks)

        u = Updatebot(configs, PROVIDERS)
        _check_jobs = functools.partial(TestFunctionality._check_jobs, u, library_filter, expected_values)

        # Ensure we don't have a dirty database with existing jobs
        tc = unittest.TestCase()
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            for task in lib.tasks:
                if task.type != 'vendoring':
                    continue
                j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
                tc.assertEqual(j, None, "When running %s, we found an existing job, indicating the database is dirty and should be cleaned." % inspect.stack()[1].function)

        return (u, expected_values, _check_jobs)

    @staticmethod
    def _cleanup(u, expected_values):
        reset_seen_counters()
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            for task in lib.tasks:
                if task.type != 'vendoring':
                    continue
                u.dbProvider.delete_job(library=lib, version=expected_values.library_new_version_id())

    @staticmethod
    def _check_jobs(u, library_filter, expected_values, status, outcome):
        tc = unittest.TestCase()

        jobs_checked = 0
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            if library_filter not in lib.name:
                continue

            for task in lib.tasks:
                if task.type != 'vendoring':
                    continue

                j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())

                tc.assertNotEqual(j, None)
                tc.assertEqual(lib.name, j.library_shortname)
                tc.assertEqual(expected_values.library_new_version_id(), j.version)
                tc.assertEqual(status, j.status, "Expected status %s, got status %s" % (status.name, j.status.name))
                tc.assertEqual(outcome, j.outcome, "Expected outcome %s, got outcome %s" % (outcome.name, j.outcome.name))
                tc.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)
                tc.assertEqual(expected_values.phab_revision_func(), j.phab_revision)
                tc.assertEqual(len(j.try_runs), 1)
                tc.assertEqual(
                    expected_values.try_revision_id(), j.try_runs[0].revision)
                tc.assertEqual('all platforms', j.try_runs[0].purpose)
                jobs_checked += 1
        tc.assertEqual(jobs_checked, 1, "We did not find a single job to check.")

    @logEntryExit
    def testAllNewJobs(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )
        try:
            u.run(library_filter=library_filter)
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    @logEntryExit
    def testPatchJob(self):

        global was_patched
        was_patched = False

        def patch_callback(cmd):
            global was_patched
            was_patched = True

        library_filter = 'png'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'patch': patch_callback}
        )
        try:
            u.run(library_filter=library_filter)
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            self.assertTrue(was_patched, "Did not successfully patch as expected.")
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Fails during ./mach vendor
    @logEntryExit
    def testFailsDuringVendor(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'vendor': lambda: raise_(Exception("No vendoring!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path'])[0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_VENDOR, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_VENDOR, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> ./mach vendor -> Fails during committing
    @logEntryExit
    def testFailsDuringCommit(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'commit': lambda: raise_(Exception("No commiting!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path'])[0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_COMMIT, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_COMMIT, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> Fails during mach vendor patch
    @logEntryExit
    def testFailsDuringPatching(self):
        library_filter = 'png'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'patch': lambda: raise_(Exception("No patching!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [l for l in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in l.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_PATCH, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_PATCH, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> mach vendor patch -> Fails during committing
    @logEntryExit
    def testFailsDuringPatchingCommit(self):
        library_filter = 'png'
        commit_calls = itertools.count()
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'patch': lambda: "",
                       'commit': lambda: "" if next(commit_calls) < 1 else raise_(Exception("No commiting the patching!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [l for l in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in l.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_COMMIT_PATCHES, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_COMMIT_PATCHES, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> Fails during try submit
    @logEntryExit
    def testFailsDuringTrySubmit(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'try_submit': lambda: raise_(Exception("No submitting to try!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [l for l in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in l.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> Fails during try submit -> make sure we don't make a new job
    @logEntryExit
    def testFailsDuringTrySubmitThenGoAgain(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'try_submit': lambda: raise_(Exception("No submitting to try!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [l for l in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in l.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

            u.run(library_filter=library_filter)
            self.assertEqual(len(u.dbProvider.get_all_jobs()), 1, "Created a job when we shouldn't")

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> try run -> Fails during phab submit
    @logEntryExit
    def testFailsDuringPhabSubmit(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'phab_submit': lambda: raise_(Exception("No submitting to phabricator!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [l for l in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in l.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    @logEntryExit
    def testAllNewJobsWithFuzzyQuery(self):
        library_filter = 'cubeb-query'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
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

    @logEntryExit
    def testAllNewJobsWithFuzzyPath(self):
        library_filter = 'cubeb-path'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'try_submit': lambda cmd: raise_(Exception("No path specified")) if "media/" not in cmd else TRY_OUTPUT(expected_values.try_revision_id(), False)}
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

    @logEntryExit
    def testFrequencyCommits(self):
        library_filter = 'cube-2commits'

        call_counter = 0

        def git_pretty_output(since_last_job):
            lines = [
                "56082fc4acfacba40993e47ef8302993c59e264f|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264e|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000",
                "62c10c170bb33f1ad6c9eb13d0cbdf13f95fb27e|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000",
            ]
            if call_counter == 0:
                return [lines[-1]]
            else:
                return lines

        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            git_pretty_output,
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: []  # filed_bug_ids_func
        )
        try:
            # Run it
            u.run(library_filter=library_filter)

            all_jobs = u.dbProvider.get_all_jobs(include_relinquished=True)
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "cube-2commits"]), 0, "I should not have created any jobs.")

            call_counter += 1

            # Run it again
            u.run(library_filter=library_filter)

            all_jobs = u.dbProvider.get_all_jobs(include_relinquished=True)
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "cube-2commits"]), 1, "I should have created a job.")
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Jobs succeeded but there are classified failures
    @logEntryExit
    def testExistingJobClassifiedFailures(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
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
        global was_abandoned
        was_abandoned = False

        def abandon_callback(cmd):
            global was_abandoned
            was_abandoned = True
            assert "83050" in cmd, "Did not see the Phabricator revision we expected to when we abandoned one."
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["55ca6286e3e4f4fba5d0448333fa99fc5a404a73|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            callbacks={'abandon': abandon_callback}
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
            self.assertTrue(was_abandoned, "Did not successfully abandon the phabricator patch.")
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Jobs are Running -> All Success
    @logEntryExit
    def testExistingJobAllSuccess(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["56082fc4acfacba40993e47ef8302993c59e264e|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
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
            lambda b: ["4173dda99ea962d907e3fa043db5e26711085ed2|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
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
            lambda b: ["ab2232a04301f1d2dbeea7050488f8ec2dde5451|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
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

    # Create -> Finish -> Create
    @logEntryExit
    def testSecondJobReferencesFirst(self):
        call_counter = 0

        def git_pretty_output(since_last_job):
            lines = [
                "56082fc4acfacba40993e47ef8302993c59e264f|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264e|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000",
                "62c10c170bb33f1ad6c9eb13d0cbdf13f95fb27e|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000",
            ]
            if call_counter == 0:
                assert not since_last_job
                return lines[1:]
            else:
                if since_last_job:
                    return lines[0:1]
                return lines

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            return 51

        def get_filed_bugs(only_open):
            if call_counter == 0:
                return []
            return [50]

        global was_abandoned
        was_abandoned = False

        def abandon_callback(cmd):
            global was_abandoned
            was_abandoned = True
            assert "83050" in cmd, "Did not see the Phabricator revision we expected to when we abandoned one."
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            git_pretty_output,
            library_filter,
            get_filed_bug_id,
            get_filed_bugs,
            callbacks={'abandon': abandon_callback}
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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertFalse(was_abandoned, "We should not have abandoned the phabricator patch.")

            call_counter += 1
            reset_seen_counters()

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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertTrue(was_abandoned, "Did not successfully abandon the phabricator patch.")
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> (Not Done) -> Create
    @logEntryExit
    def testSecondJobButFirstIsntDone(self):
        call_counter = 0

        def git_pretty_output(since_last_job):
            lines = [
                "56082fc4acfacba40993e47ef8302993c59e264f|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264e|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000",
                "62c10c170bb33f1ad6c9eb13d0cbdf13f95fb27e|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000",
            ]
            if call_counter == 0:
                assert not since_last_job
                return lines[1:]
            else:
                if since_last_job:
                    return lines[0:1]
                return lines

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            return 51

        def get_filed_bugs(only_open):
            if call_counter == 0:
                return []
            return [50]

        global was_abandoned
        was_abandoned = False

        def abandon_callback(cmd):
            global was_abandoned
            was_abandoned = True
            assert "83050" in cmd, "Did not see the Phabricator revision we expected to when we abandoned one."
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            git_pretty_output,
            library_filter,
            get_filed_bug_id,
            get_filed_bugs,
            callbacks={'abandon': abandon_callback}
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            call_counter += 1
            reset_seen_counters()

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully, and aborted the other one
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            all_jobs = u.dbProvider.get_all_jobs(include_relinquished=True)
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ABORTED, "The first job should be set as Aborted.")
            self.assertTrue(was_abandoned, "We did not abandon the phabricator revision as expected.")

            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it a build job failed
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Finish -> Create -> Finish -> Create
    @logEntryExit
    def testThreeJobs(self):
        call_counter = 0

        def git_pretty_output(since_last_job):
            lines = [
                "56082fc4acfacba40993e47ef8302993c59e264f|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264e|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264d|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000",
            ]
            if call_counter == 0:
                assert not since_last_job
                return lines[2:]
            elif call_counter == 1:
                if since_last_job:
                    return lines[1:2]
                return lines[1:]
            else:
                if since_last_job:
                    return lines[0:1]
                return lines

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            elif call_counter == 1:
                return 51
            return 52

        def get_filed_bugs(only_open):
            if call_counter == 0:
                return []
            elif call_counter == 1:
                return [50]
            elif only_open:
                return [51]
            return [50, 51]

        global abandon_count
        abandon_count = 0

        def abandon_callback(cmd):
            global abandon_count
            abandon_count += 1
            expected = str(83000 + get_filed_bug_id() - 1)
            assert expected in cmd, "Did not see the Phabricator revision we expected (%s) to when we abandoned one (%s)." % (expected, cmd)
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            git_pretty_output,
            library_filter,
            get_filed_bug_id,
            get_filed_bugs,
            callbacks={'abandon': abandon_callback}
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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 0, "We prematurely abandoned the phabricator revision.")

            call_counter += 1
            reset_seen_counters()

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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 1, "We did not abandon the phabricator revision as expected.")

            call_counter += 1
            reset_seen_counters()

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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 2, "We did not abandon the phabricator revision as expected.")
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> (Not Done) -> Create -> (Not Done) -> Create
    @logEntryExit
    def testThreeJobsButDontLetThemFinish(self):
        call_counter = 0

        def git_pretty_output(since_last_job):
            lines = [
                "56082fc4acfacba40993e47ef8302993c59e264f|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264e|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264d|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000",
            ]
            if call_counter == 0:
                assert not since_last_job
                return lines[2:]
            elif call_counter == 1:
                if since_last_job:
                    return lines[1:2]
                return lines[1:]
            else:
                if since_last_job:
                    return lines[0:1]
                return lines

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            elif call_counter == 1:
                return 51
            return 52

        def get_filed_bugs(only_open):
            if call_counter == 0:
                return []
            elif call_counter == 1:
                return [50]
            elif only_open:
                return [51]
            return [50, 51]

        global abandon_count
        abandon_count = 0

        def abandon_callback(cmd):
            global abandon_count
            abandon_count += 1
            expected = str(83000 + get_filed_bug_id() - 1)
            assert expected in cmd, "Did not see the Phabricator revision we expected (%s) to when we abandoned one (%s)." % (expected, cmd)
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            git_pretty_output,
            library_filter,
            get_filed_bug_id,
            get_filed_bugs,
            callbacks={'abandon': abandon_callback}
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            call_counter += 1
            reset_seen_counters()

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully, and aborted the other one
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            all_jobs = u.dbProvider.get_all_jobs(include_relinquished=True)
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ABORTED, "The first job should be set as Aborted.")
            self.assertEqual(abandon_count, 1, "We did not abandon the phabricator revision as expected.")

            call_counter += 1
            reset_seen_counters()

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully, and aborted the other one
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            all_jobs = u.dbProvider.get_all_jobs(include_relinquished=True)
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 3, "I should have created three jobs.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ABORTED, "The first job should be set as Aborted.")
            self.assertEqual(all_jobs[2].outcome, JOBOUTCOME.ABORTED, "The first job should be set as Aborted.")
            self.assertEqual(abandon_count, 2, "We did not abandon the phabricator revision as expected.")

            # Run it again, this time we'll tell it the jobs are still in process
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it a build job failed
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 2, "We over abandoned the phabricator revision as expected.")
        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> All Success -> Bump FF Version
    @logEntryExit
    def testBumpFFVersion(self):
        call_counter = 0

        def filed_bug_ids(only_open):
            if call_counter == 0:
                return []
            return [50]

        global was_marked_affected
        was_marked_affected = False

        def assert_affected(bug_id, ff_version, affected):
            global was_marked_affected
            was_marked_affected = True
            affected_str = "affected" if affected else "unaffected"
            assert affected, "Marked %s as %s for %s when we shouldn't have." % (bug_id, affected_str, ff_version)

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            lambda b: ["56082fc4acfacba40993e47ef8302993c59e264e|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            library_filter,
            lambda: 50,  # get_filed_bug_id_func,
            filed_bug_ids,
            assert_affected_func=assert_affected,
            keep_tmp_db=True
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
            self.assertFalse(was_marked_affected)

            old_ff_version = u.config_dictionary['General']['ff-version']
            config_dictionary = copy.deepcopy(u.config_dictionary)
            config_dictionary['Database']['keep_tmp_db'] = False
            config_dictionary['General']['ff-version'] += 1
            config_dictionary['General']['repo'] = "https://hg.mozilla.org/mozilla-beta"

            u = Updatebot(config_dictionary, PROVIDERS)

            # Run it
            u.run(library_filter=library_filter)
            all_jobs = u.dbProvider.get_all_jobs(include_relinquished=True)
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 1, "I should still have one job.")
            self.assertEqual(all_jobs[0].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the second bug")
            self.assertTrue(was_marked_affected)

        finally:
            TestFunctionality._cleanup(u, expected_values)

    # Create -> Finish -> Create -> Finish -> Bugzilla Reopens Bug #1 -> Create
    @logEntryExit
    def testThreeJobsReopenFirst(self):
        call_counter = 0

        def git_pretty_output(since_last_job):
            lines = [
                "56082fc4acfacba40993e47ef8302993c59e264f|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264e|2020-11-12 10:01:18 +0000|2020-11-12 13:10:14 +0000",
                "56082fc4acfacba40993e47ef8302993c59e264d|2020-11-12 07:00:44 +0000|2020-11-12 08:44:21 +0000",
            ]
            if call_counter == 0:
                assert not since_last_job
                return lines[2:]
            elif call_counter == 1:
                if since_last_job:
                    return lines[1:2]
                return lines[1:]
            else:
                if since_last_job:
                    return lines[0:1]
                return lines

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            elif call_counter == 1:
                return 51
            return 52

        def get_filed_bugs(only_open):
            if call_counter == 0:
                return []
            elif call_counter == 1:
                return [50]
            elif only_open:
                return [50, 51]
            return [50, 51]

        global abandon_count
        abandon_count = 0

        def abandon_callback(cmd):
            global abandon_count
            abandon_count += 1
            expected = str(83000 + get_filed_bug_id() - 1)
            assert expected in cmd, "Did not see the Phabricator revision we expected (%s) to when we abandoned one (%s)." % (expected, cmd)
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = TestFunctionality._setup(
            git_pretty_output,
            library_filter,
            get_filed_bug_id,
            get_filed_bugs,
            callbacks={'abandon': abandon_callback}
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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 0, "We prematurely abandoned the phabricator revision.")

            call_counter += 1
            reset_seen_counters()

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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 1, "We did not abandon the phabricator revision as expected.")

            call_counter += 1
            reset_seen_counters()

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
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 2, "We did not abandon the phabricator revision as expected.")
        finally:
            TestFunctionality._cleanup(u, expected_values)


if __name__ == '__main__':
    unittest.main(verbosity=0)
