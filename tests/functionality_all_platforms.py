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

from components.utilities import Struct, raise_, AssertFalse
from components.logging import SimpleLoggingTest, LoggingProvider, log, logEntryExitHeaderLine
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS, JOBOUTCOME
from components.mach_vendor import VendorProvider
from components.hg import MercurialProvider
from components.scmprovider import SCMProvider
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

from tests.functionality_utilities import SHARED_COMMAND_MAPPINGS, TRY_OUTPUT, CONDUIT_EDIT_OUTPUT, MockedBugzillaProvider, treeherder_response
from tests.mock_commandprovider import TestCommandProvider
from tests.mock_libraryprovider import MockLibraryProvider
from tests.mock_treeherder_server import MockTreeherderServerFactory, TYPE_HEALTH
from tests.database import transform_db_config_to_tmp_db

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)


def DEFAULT_EXPECTED_VALUES(git_pretty_output_func, get_filed_bug_id_func, two_phab_revisions):
    return Struct(**{
        'git_pretty_output_func': git_pretty_output_func,
        'library_new_version_id': lambda: git_pretty_output_func(False)[0].split("|")[0],
        'try_revision_id': lambda: git_pretty_output_func(False)[0].split("|")[0],
        'get_filed_bug_id_func': get_filed_bug_id_func,
        'phab_revision_func': lambda: 83000 + get_filed_bug_id_func(),
        'two_phab_revisions': two_phab_revisions
    })


def COMMAND_MAPPINGS(expected_values, command_callbacks):
    ret = SHARED_COMMAND_MAPPINGS(expected_values, command_callbacks)
    ret["./mach try auto"] = command_callbacks.get('try_submit', lambda: TRY_OUTPUT(expected_values.try_revision_id()))
    ret["./mach try fuzzy"] = command_callbacks.get('try_submit', lambda: TRY_OUTPUT(expected_values.try_revision_id(), False))
    ret["./mach try --update --preset"] = command_callbacks.get('try_submit', lambda: TRY_OUTPUT(expected_values.try_revision_id(), False))
    return ret


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
    def _setup(self,
               library_filter,
               git_pretty_output_func,
               get_filed_bug_id_func,
               filed_bug_ids_func,
               treeherder_response,
               two_phab_revisions=False,
               assert_affected_func=None,
               command_callbacks={},
               keep_tmp_db=False):
        self.server = server.HTTPServer(('', 27490), MockTreeherderServerFactory(treeherder_response))
        t = Thread(target=self.server.serve_forever)
        t.start()

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

        expected_values = DEFAULT_EXPECTED_VALUES(git_pretty_output_func, get_filed_bug_id_func, two_phab_revisions)
        configs['Command']['test_mappings'] = COMMAND_MAPPINGS(expected_values, command_callbacks)

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

    def _cleanup(self, u, expected_values):
        self.server.shutdown()
        self.server.server_close()
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
                log("In _check_jobs looking for status %s and outcome %s" % (status, outcome))

                tc.assertNotEqual(j, None)
                tc.assertEqual(lib.name, j.library_shortname)
                tc.assertEqual(expected_values.library_new_version_id(), j.version)
                tc.assertEqual(status, j.status, "Expected status %s, got status %s" % (status.name, j.status.name))
                tc.assertEqual(outcome, j.outcome, "Expected outcome %s, got outcome %s" % (outcome.name, j.outcome.name))
                tc.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

                tc.assertEqual(len(j.phab_revisions), 2 if expected_values.two_phab_revisions else 1)
                tc.assertEqual(expected_values.phab_revision_func(), j.phab_revisions[0].revision)
                tc.assertEqual('vendoring commit', j.phab_revisions[0].purpose)
                if expected_values.two_phab_revisions:
                    tc.assertEqual(expected_values.phab_revision_func() + 1, j.phab_revisions[1].revision)
                    tc.assertEqual('patches commit', j.phab_revisions[1].purpose)

                tc.assertEqual(len(j.try_runs), 1)
                tc.assertEqual(
                    expected_values.try_revision_id(), j.try_runs[0].revision)
                tc.assertEqual('all platforms', j.try_runs[0].purpose)
                jobs_checked += 1
        tc.assertEqual(jobs_checked, 1, "Did not find a single job to check")

    @logEntryExitHeaderLine
    def testAllNewJobs(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse  # treeherder_response
        )
        try:
            u.run(library_filter=library_filter)
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
        finally:
            self._cleanup(u, expected_values)

    @logEntryExitHeaderLine
    def testPatchJob(self):
        global was_patched
        was_patched = False

        def patch_callback(cmd):
            global was_patched
            was_patched = True

        library_filter = 'png'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            two_phab_revisions=True,
            command_callbacks={'patch': patch_callback}
        )
        try:
            u.run(library_filter=library_filter)
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            self.assertTrue(was_patched, "Did not successfully patch as expected.")
        finally:
            self._cleanup(u, expected_values)

    # Create -> Fails during ./mach vendor
    @logEntryExitHeaderLine
    def testFailsDuringVendor(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'vendor': lambda: raise_(Exception("No vendoring!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_VENDOR, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_VENDOR, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            self._cleanup(u, expected_values)

    # Create -> ./mach vendor -> Fails during committing
    @logEntryExitHeaderLine
    def testFailsDuringCommit(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'commit': lambda: raise_(Exception("No committing!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_COMMIT, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_COMMIT, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            self._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> Fails during mach vendor patch
    @logEntryExitHeaderLine
    def testFailsDuringPatching(self):
        library_filter = 'png'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'patch': lambda: raise_(Exception("No patching!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_PATCH, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_PATCH, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            self._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> mach vendor patch -> Fails during committing
    @logEntryExitHeaderLine
    def testFailsDuringPatchingCommit(self):
        library_filter = 'png'
        commit_calls = itertools.count()
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'patch': lambda: "",
                               'commit': lambda: "" if next(commit_calls) < 1 else raise_(Exception("No commiting the patching!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_COMMIT_PATCHES, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_COMMIT_PATCHES, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            self._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> Fails during try submit
    @logEntryExitHeaderLine
    def testFailsDuringTrySubmit(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'try_submit': lambda: raise_(Exception("No submitting to try!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

        finally:
            self._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> Fails during try submit -> make sure we don't make a new job
    @logEntryExitHeaderLine
    def testFailsDuringTrySubmitThenGoAgain(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'try_submit': lambda: raise_(Exception("No submitting to try!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_SUBMIT_TO_TRY, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)

            u.run(library_filter=library_filter)
            self.assertEqual(len(u.dbProvider.get_all_jobs()), 1, "Created a job when we shouldn't")

        finally:
            self._cleanup(u, expected_values)

    # Create -> ./mach vendor -> commit -> try run -> Fails during phab submit
    @logEntryExitHeaderLine
    def testFailsDuringPhabSubmit(self):
        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["try_rev|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse,  # treeherder_response
            command_callbacks={'phab_submit': lambda: raise_(Exception("No submitting to phabricator!"))}
        )
        try:
            u.run(library_filter=library_filter)

            # Cannot use the provided _check_jobs
            lib = [lib for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']) if library_filter in lib.name][0]
            j = u.dbProvider.get_job(lib, expected_values.library_new_version_id())
            self.assertEqual(expected_values.library_new_version_id(), j.version)
            self.assertEqual(JOBSTATUS.DONE, j.status, "Expected status JOBSTATUS.DONE, got status %s" % (j.status.name))
            self.assertEqual(JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB, j.outcome, "Expected outcome JOBOUTCOME.COULD_NOT_SUBMIT_TO_PHAB, got outcome %s" % (j.outcome.name))
            self.assertEqual(expected_values.get_filed_bug_id_func(), j.bugzilla_id)
        finally:
            self._cleanup(u, expected_values)

    @logEntryExitHeaderLine
    def testAllNewPresetJobs(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_classified_failures.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_classified_failures.txt"

        library_filter = 'cubeb-preset'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder
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
            self._cleanup(u, expected_values)

    @logEntryExitHeaderLine
    def testAllNewFuzzyQueryJobs(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_classified_failures.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_classified_failures.txt"

        library_filter = 'cubeb-query'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder
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
            self._cleanup(u, expected_values)

    @logEntryExitHeaderLine
    def testAllNewFuzzyPathJobs(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_classified_failures.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_classified_failures.txt"

        library_filter = 'cubeb-path'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder,
            command_callbacks={'try_submit': lambda cmd: raise_(Exception("No path specified")) if "media/" not in cmd else TRY_OUTPUT(expected_values.try_revision_id(), False)}
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
            self._cleanup(u, expected_values)

    @logEntryExitHeaderLine
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

        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            git_pretty_output,
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            AssertFalse
        )
        try:
            # Run it
            u.run(library_filter=library_filter)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "cube-2commits"]), 0, "I should not have created any jobs.")

            call_counter += 1

            # Run it again
            u.run(library_filter=library_filter)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "cube-2commits"]), 1, "I should have created a job.")
        finally:
            self._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Jobs succeeded but there are classified failures
    @logEntryExitHeaderLine
    def testExistingJobClassifiedFailures(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_classified_failures.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_classified_failures.txt"

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["e152bb86666565ee6619c15f60156cd6c79580a9|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder
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
            self._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Build Failed
    @logEntryExitHeaderLine
    def testExistingJobBuildFailed(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                self.assertFalse(True, "Should not have requested this")
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "build_failed.txt"

        global was_abandoned
        was_abandoned = False

        def abandon_callback(cmd):
            global was_abandoned
            was_abandoned = True
            assert "83050" in cmd, "Did not see the Phabricator revision we expected to when we abandoned one."
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["55ca6286e3e4f4fba5d0448333fa99fc5a404a73|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder,
            command_callbacks={'abandon': abandon_callback}
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
            self._cleanup(u, expected_values)

    # Create -> Jobs are Running -> All Success
    @logEntryExitHeaderLine
    def testExistingJobAllSuccess(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_all_success.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_all_success.txt"

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["56082fc4acfacba40993e47ef8302993c59e264e|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder
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
            self._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Same test on multiple platforms -> Unclassified Failure
    @logEntryExitHeaderLine
    def testExistingJobUnclassifiedFailureNoRetriggers(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_unclassified_failures_multiple_per_test.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_unclassified_failures_multiple_per_test.txt"

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["4173dda99ea962d907e3fa043db5e26711085ed2|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            lambda b: [],  # filed_bug_ids_func
            treeherder
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
            self._cleanup(u, expected_values)

    # Create -> Jobs are Running -> Awaiting Retriggers -> Unclassified Failure
    @logEntryExitHeaderLine
    def testExistingJobUnclassifiedFailuresNeedingRetriggers(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_unclassified_failures_before_retriggers.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                elif treeherder.jobs_calls == 1:
                    return "jobs_unclassified_failures_before_retriggers.txt"
                return "jobs_unclassified_failures_after_retriggers.txt"

        call_counter = 0

        def get_filed_bugs(only_open):
            if call_counter == 0:
                return []
            elif call_counter == 1:
                return [50]

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["ab2232a04301f1d2dbeea7050488f8ec2dde5451|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            lambda: 50,  # get_filed_bug_id_func,
            get_filed_bugs,
            treeherder
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

            # Needed because get_filed_bugs needs to tell Updatebot that the bug we just filed is open
            # so we advance to retrigger instead of just stopping here.
            call_counter += 1

            # Run it again, this time we'll tell it a test failed
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.AWAITING_RETRIGGER_RESULTS, JOBOUTCOME.PENDING)

            # Run it again, this time we'll tell it all the tests failed
            u.run(library_filter=library_filter)
            # Should be DONE and Failed.
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)
        finally:
            self._cleanup(u, expected_values)

    # Create -> Finish -> Create
    @logEntryExitHeaderLine
    def testSecondJobReferencesFirst(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_all_success.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_all_success.txt"

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
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            git_pretty_output,
            get_filed_bug_id,
            get_filed_bugs,
            treeherder,
            command_callbacks={'abandon': abandon_callback}
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
            # Run it again, this time it'll be successful
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertFalse(was_abandoned, "We should not have abandoned the phabricator patch.")

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it we'll tell it it succeeded right away
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if library_filter in j.library_shortname]), 2, "I should have two jobs.")
            self.assertEqual(all_jobs[0].outcome, JOBOUTCOME.ALL_SUCCESS, "The second job should still be successful.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ALL_SUCCESS, "The first job should still be successful.")
            self.assertTrue(all_jobs[1].relinquished, "The first job should be relinquished.")
            self.assertTrue(was_abandoned, "Did not successfully abandon the phabricator patch.")
        finally:
            self._cleanup(u, expected_values)

    # Create -> (Not Done) -> Create
    @logEntryExitHeaderLine
    def testSecondJobButFirstIsntDone(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_all_success.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_all_success.txt"

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
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            git_pretty_output,
            get_filed_bug_id,
            get_filed_bugs,
            treeherder,
            command_callbacks={'abandon': abandon_callback}
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully, and relinquished the first one
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if library_filter in j.library_shortname]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, "The first job should still be pending.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.PENDING, "The first job should still be pending.")
            self.assertTrue(all_jobs[1].relinquished, "The first job should be relinquished.")
            self.assertTrue(was_abandoned, "We should have abandoned the phabricator revision as expected.")

            call_counter += 1

            # Run it again
            u.run(library_filter=library_filter)
            # Check that both jobs finished
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if library_filter in j.library_shortname]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].status, JOBSTATUS.DONE, "The first job should still be done.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ALL_SUCCESS, "The first job should be success.")
            self.assertTrue(all_jobs[1].relinquished, "The first job should be relinquished.")
        finally:
            self._cleanup(u, expected_values)

    # Create -> Finish -> Create -> Finish -> Create
    @logEntryExitHeaderLine
    def testThreeJobsSimple(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_all_success.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "jobs_all_success.txt"

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
            elif call_counter == 2:
                if only_open:
                    return [51]
                return [50, 51]
            self.assertFalse(True)

        global abandon_count
        abandon_count = 0

        def abandon_callback(cmd):
            global abandon_count
            abandon_count += 1
            expected = str(83000 + get_filed_bug_id() - 1)
            assert expected in cmd, "Did not see the Phabricator revision we expected (%s) to when we abandoned one (%s)." % (expected, cmd)
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            git_pretty_output,
            get_filed_bug_id,
            get_filed_bugs,
            treeherder,
            command_callbacks={'abandon': abandon_callback}
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
            # Run it again, this time we'll tell it it's finally done
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            self.assertEqual(abandon_count, 0, "We prematurely abandoned the phabricator revision.")

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            # Run it again, this time we'll tell it it's done
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if library_filter in j.library_shortname]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].status, JOBSTATUS.DONE, "The first job should be done.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ALL_SUCCESS, "The first job should be success.")
            self.assertTrue(all_jobs[1].relinquished, "The first job should be relinquished.")
            self.assertEqual(abandon_count, 1, "We did not abandon the phabricator revision as expected.")

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            # Run it again, this time we'll tell it it's done
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)
            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if library_filter in j.library_shortname]), 3, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].status, JOBSTATUS.DONE, "The second job should be done.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ALL_SUCCESS, "The second job should be success.")
            self.assertTrue(all_jobs[1].relinquished, "The second job should be relinquished.")
            self.assertEqual(abandon_count, 2, "We did not abandon the phabricator revision as expected.")
        finally:
            self._cleanup(u, expected_values)

    # Create -> (Not Done) -> Create -> (Not Done) -> Create
    @logEntryExitHeaderLine
    def testThreeJobsButDontLetThemFinish(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                return "health_all_success.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls < 3:
                    return "jobs_still_running.txt"
                return "jobs_all_success.txt"

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
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            git_pretty_output,
            get_filed_bug_id,
            get_filed_bugs,
            treeherder,
            command_callbacks={'abandon': abandon_callback}
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the second job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if library_filter in j.library_shortname]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.PENDING, "The first job should not be done yet.")
            self.assertEqual(all_jobs[1].status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, "The first job should be pending.")
            self.assertTrue(all_jobs[1].relinquished, "The first job should be relinquished.")
            self.assertEqual(abandon_count, 1, "We did not abandon the phabricator revision as expected.")

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the third job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 3, "I should have created three jobs.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.PENDING, "The second job should still be pending.")
            self.assertEqual(all_jobs[2].outcome, JOBOUTCOME.PENDING, "The first job should still be pending.")
            self.assertEqual(abandon_count, 2, "We did not abandon the phabricator revision as expected.")

            # Run it again, this time we'll tell it the jobs are finally done
            u.run(library_filter=library_filter)
            # Should be DONE and Success
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.ALL_SUCCESS)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 3, "I should have created three jobs.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.ALL_SUCCESS, "The second job should be done.")
            self.assertEqual(all_jobs[2].outcome, JOBOUTCOME.ALL_SUCCESS, "The first job should be done.")
            self.assertEqual(abandon_count, 2, "We over abandoned the phabricator revision.")
        finally:
            self._cleanup(u, expected_values)

    # Create -> All Success -> Bump FF Version
    @logEntryExitHeaderLine
    def testBumpFFVersion(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                self.assertFalse(True, "Should not be called")
            else:  # TYPE_JOBS
                if treeherder.jobs_calls == 0:
                    return "jobs_still_running.txt"
                return "build_failed.txt"

        call_counter = 0

        def get_filed_bug_id():
            return 50

        def get_filed_bugs(only_open):
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

        global abandon_count
        abandon_count = 0

        def abandon_callback(cmd):
            global abandon_count
            abandon_count += 1
            expected = str(83000 + get_filed_bug_id())
            assert expected in cmd, "Did not see the Phabricator revision we expected (%s) to when we abandoned one (%s)." % (expected, cmd)
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            lambda b: ["56082fc4acfacba40993e47ef8302993c59e264e|2021-02-09 15:30:04 -0500|2021-02-12 17:40:01 +0000"],
            get_filed_bug_id,
            get_filed_bugs,
            treeherder,
            command_callbacks={'abandon': abandon_callback},
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
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.BUILD_FAILED)
            self.assertFalse(was_marked_affected)

            old_ff_version = u.config_dictionary['General']['ff-version']
            config_dictionary = copy.deepcopy(u.config_dictionary)
            config_dictionary['Database']['keep_tmp_db'] = False
            config_dictionary['General']['ff-version'] += 1
            config_dictionary['General']['repo'] = "https://hg.mozilla.org/mozilla-beta"

            u = Updatebot(config_dictionary, PROVIDERS)

            call_counter += 1

            # Run it
            u.run(library_filter=library_filter)
            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 1, "I should still have one job.")
            self.assertEqual(all_jobs[0].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the second bug")
            self.assertTrue(was_marked_affected)

        finally:
            self._cleanup(u, expected_values)

    # Create -> Create -> Bugzilla Reopens Bug #1 -> Create -> Finish
    @logEntryExitHeaderLine
    def testThreeJobsReopenFirst(self):
        @treeherder_response
        def treeherder(request_type, fullpath):
            if request_type == TYPE_HEALTH:
                # We don't actually have a health response for failures after retriggers, but it doesn't matter
                return "health_unclassified_failures_before_retriggers.txt"
            else:  # TYPE_JOBS
                if treeherder.jobs_calls < 3:
                    return "jobs_still_running.txt"
                # It actually doesn't care if it gets the before or after file, as long as the jobs aren't running
                elif treeherder.jobs_calls < 6:
                    return "jobs_unclassified_failures_before_retriggers.txt"
                return "jobs_unclassified_failures_after_retriggers.txt"

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
            elif call_counter == 2:
                if only_open:
                    return [50, 51]
                return [50, 51]
            elif call_counter == 3:
                if only_open:
                    # This is the important bit: the first bug is open, the second is closed.
                    return [50, 52]
                return [50, 51, 52]
            else:
                self.assertTrue(False, "Should not have reached here")

        global abandon_count
        abandon_count = 0

        def abandon_callback(cmd):
            global abandon_count
            abandon_count += 1
            expected = str(83000 + get_filed_bug_id() - 1)
            assert expected in cmd, "Did not see the Phabricator revision we expected (%s) to when we abandoned one (%s)." % (expected, cmd)
            return CONDUIT_EDIT_OUTPUT

        library_filter = 'dav1d'
        (u, expected_values, _check_jobs) = self._setup(
            library_filter,
            git_pretty_output,
            get_filed_bug_id,
            get_filed_bugs,
            treeherder,
            command_callbacks={'abandon': abandon_callback}
        )

        try:
            # Run it
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)
            self.assertEqual(abandon_count, 0, "We prematurely abandoned the phabricator revision.")

            call_counter += 1

            # Run it.  In doing so we will close the first bug
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            # Check that the first job is in the correct state
            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 2, "I should have created two jobs.")
            self.assertEqual(all_jobs[1].status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, "The first job should be awaiting results.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.PENDING, "The first job should be awaiting results.")
            self.assertTrue(all_jobs[1].relinquished, "The first job should be relinquished.")
            self.assertEqual(abandon_count, 1, "We did not abandon the phabricator revision as expected.")

            call_counter += 1

            # Run it. We will close the second bug, but the first bug will get reopened via get_filed_bugs.
            u.run(library_filter=library_filter)
            # Check that we created the job successfully
            _check_jobs(JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, JOBOUTCOME.PENDING)

            # Check that the first job is in the correct state
            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 3, "I should have created three jobs.")
            self.assertEqual(all_jobs[2].status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, "The first job should be awaiting results.")
            self.assertEqual(all_jobs[2].outcome, JOBOUTCOME.PENDING, "The first job should be awaiting results.")
            self.assertTrue(all_jobs[2].relinquished, "The first job should be relinquished.")

            # Check that the second job is in the correct state
            self.assertEqual(all_jobs[1].status, JOBSTATUS.AWAITING_SECOND_PLATFORMS_TRY_RESULTS, "The second job should be awaiting results.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.PENDING, "The second job should be awaiting results.")
            self.assertTrue(all_jobs[1].relinquished, "The second job should be relinquished.")
            self.assertEqual(abandon_count, 2, "We did not abandon the phabricator revision as expected.")

            call_counter += 1

            # Run it again, this time we'll tell it the jobs have unclassified failures and need a retrigger.
            # This should put the first job into that state, but the second job's bug stayed closed and it won't do any retriggers.
            u.run(library_filter=library_filter)
            # Should still be Awaiting Try Results
            _check_jobs(JOBSTATUS.AWAITING_RETRIGGER_RESULTS, JOBOUTCOME.PENDING)
            self.assertEqual(abandon_count, 2, "We over-abandoned phabricator revisions.")

            # Check that the first job is in the correct state
            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 3, "I should have created three jobs.")
            self.assertEqual(all_jobs[2].status, JOBSTATUS.AWAITING_RETRIGGER_RESULTS, "The first job should be awaiting retrigger results.")
            self.assertEqual(all_jobs[2].outcome, JOBOUTCOME.PENDING, "The first job should be awaiting results.")
            self.assertTrue(all_jobs[2].relinquished, "The first job should be relinquished.")

            # Check that the second job is in the correct state
            self.assertEqual(all_jobs[1].status, JOBSTATUS.DONE, "The second job should be awaiting results.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.UNCLASSIFIED_FAILURES, "The second job should be awaiting results.")
            self.assertTrue(all_jobs[1].relinquished, "The second job should be relinquished.")

            # Run it again, this time we'll finish the retriggers
            # This should put the first job into that state, but the second job's bug stayed closed and it won't do any retriggers.
            u.run(library_filter=library_filter)
            # Third Job should be DONE
            _check_jobs(JOBSTATUS.DONE, JOBOUTCOME.UNCLASSIFIED_FAILURES)

            all_jobs = u.dbProvider.get_all_jobs()
            self.assertEqual(len([j for j in all_jobs if j.library_shortname == "dav1d"]), 3, "I should have created three jobs.")
            self.assertEqual(all_jobs[2].status, JOBSTATUS.DONE, "The first job should be awaiting retrigger results.")
            self.assertEqual(all_jobs[2].outcome, JOBOUTCOME.UNCLASSIFIED_FAILURES, "The first job should be awaiting results.")
            self.assertTrue(all_jobs[2].relinquished, "The first job should be relinquished.")

            # Check that the second job is in the correct state
            self.assertEqual(all_jobs[1].status, JOBSTATUS.DONE, "The second job should be awaiting results.")
            self.assertEqual(all_jobs[1].outcome, JOBOUTCOME.UNCLASSIFIED_FAILURES, "The second job should be awaiting results.")
            self.assertTrue(all_jobs[1].relinquished, "The second job should be relinquished.")
        finally:
            self._cleanup(u, expected_values)


if __name__ == '__main__':
    unittest.main(verbosity=0)
