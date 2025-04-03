#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import copy
import inspect
import unittest
import functools

sys.path.append(".")
sys.path.append("..")
import components.utilities
components.utilities.RETRY_TIMES = 2

from automation import Updatebot

from components.utilities import Struct, NeverUseMeClass
from components.providerbase import BaseProvider
from components.logging import SimpleLogger, SimpleLoggingTest, LoggingProvider, log, logEntryExit
from components.dbc import DatabaseProvider
from components.dbmodels import JOBTYPE, JOBSTATUS, JOBOUTCOME
from components.scmprovider import SCMProvider
from components.commandprovider import CommandProvider

from tests.mock_commandprovider import TestCommandProvider, DO_EXECUTE
from tests.mock_libraryprovider import MockLibraryProvider
from tests.mock_repository import COMMITS_BRANCH1, COMMITS_MAIN
from tests.database import transform_db_config_to_tmp_db

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)

# They are ordered newest to oldest, so we need to invert the number


def GENERIC_EXPECTED_COMMITS_SEEN(get_next_lib_revision, get_current_lib_revision):
    return - (COMMITS_BRANCH1.index(get_next_lib_revision()) - COMMITS_BRANCH1.index(get_current_lib_revision())) if get_next_lib_revision() else 0


def DEFAULT_EXPECTED_VALUES(new_library_version_func, get_filed_bug_id_func):
    return Struct(**{
        'new_version_id': new_library_version_func,
        'get_filed_bug_id_func': get_filed_bug_id_func,
    })


def AssertFalse(a=False, b=False, c=False):
    assert False, "We should not have called this function in this test."


def COMMAND_MAPPINGS(expected_values):
    return {
        "git": DO_EXECUTE
    }


ALL_BUGS = False
ONLY_OPEN = True


class MockedBugzillaProvider(BaseProvider):
    def __init__(self, config):
        self.config = config
        self._expected_commits_seen_func = config['expected_commits_seen_func']
        self._get_filed_bug_id_func = config['get_filed_bug_id_func']
        self._filed_bug_ids_func = config['filed_bug_ids_func']
        if config['assert_affected_func']:
            self._assert_affected_func = config['assert_affected_func']
        else:
            self._assert_affected_func = AssertFalse

    def file_bug(self, library, summary, description, cc_list, needinfo=None, see_also=None, depends_on=None, blocks=None, moco_confidential=False):
        expected_summary_str = str(self._expected_commits_seen_func()) + " new commits"
        assert expected_summary_str in summary, \
            "We did not see the expected number of commits in the bug we filed. Expected '%s', summary is '%s'" % (expected_summary_str, summary)

        have_prior_bugs = len(self._filed_bug_ids_func(ALL_BUGS)) > 0
        assert not have_prior_bugs or depends_on == self._filed_bug_ids_func(ALL_BUGS)[-1], \
            "We did not set the depends_on correctly when we filed the bug. Expected %s got %s" % (
            (self._filed_bug_ids_func(ALL_BUGS)[-1] if have_prior_bugs else "no depends"), depends_on)

        references_prior_bug = "This list only contains new commits, it looks like" in description
        if have_prior_bugs and len(self._filed_bug_ids_func(ONLY_OPEN)) > 0:
            assert references_prior_bug, \
                "We did not see the expected reference to prior open bugs we expected to see. Description: " + description
        else:
            assert not references_prior_bug, \
                "We saw a reference to a prior bug we did not expect to see. Description: " + description

        return self._get_filed_bug_id_func()

    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        pass

    def wontfix_bug(self, bug_id, comment):
        pass

    def dupe_bug(self, bug_id, comment, dup_id):
        pass

    def find_open_bugs_info(self, bug_ids):
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
    # Fully Mocked, avoids needing to make a fake
    # bugzilla server which provides no additional logic coverage
    'Bugzilla': MockedBugzillaProvider,
    # Fully mocked
    'Library': MockLibraryProvider,
    # Not mocked
    'SCM': SCMProvider,
    'Mercurial': NeverUseMeClass,
    'Taskcluster': NeverUseMeClass,
    'Vendor': NeverUseMeClass,
    'Phabricator': NeverUseMeClass,
}


class TestFunctionality(SimpleLoggingTest):
    @staticmethod
    def _setup(current_library_version_func,
               new_library_version_func,
               expected_commits_seen_func,
               get_filed_bug_id_func,
               filed_bug_ids_func,
               library_filter,
               assert_affected_func=None,
               branch="master",
               repo_func=None,
               keep_tmp_db=False):
        real_command_runner = CommandProvider({})
        real_command_runner.update_config({
            'LoggingProvider': SimpleLogger(localconfig['Logging'])
        })

        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        db_config['keep_tmp_db'] = keep_tmp_db
        configs = {
            'General': {
                'env': 'dev',
                'gecko-path': '.',
                'ff-version': 87,
                'repo': 'https://hg.mozilla.org/mozilla-central'
            },
            'Command': {
                'test_mappings': None,
                'real_runner': real_command_runner
            },
            'Logging': localconfig['Logging'],
            'Database': db_config,
            'Vendor': {},
            'Bugzilla': {
                'expected_commits_seen_func': expected_commits_seen_func,
                'get_filed_bug_id_func': get_filed_bug_id_func,
                'filed_bug_ids_func': filed_bug_ids_func,
                'assert_affected_func': assert_affected_func
            },
            'Mercurial': {},
            'Taskcluster': {},
            'Phabricator': {},
            'Library': {
                'commitalert_revision_override': current_library_version_func,
                'commitalert_repo_override': repo_func,
                'commitalert_branch_override': branch
            }
        }

        expected_values = DEFAULT_EXPECTED_VALUES(new_library_version_func, get_filed_bug_id_func)
        configs['Command']['test_mappings'] = COMMAND_MAPPINGS(expected_values)

        u = Updatebot(configs, PROVIDERS)

        # Ensure we don't have a dirty database with existing jobs
        tc = unittest.TestCase()
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            j = u.dbProvider.get_job(lib, expected_values.new_version_id())
            tc.assertEqual(j, None, "When running %s, we found an existing job, indicating the database is dirty and should be cleaned." % inspect.stack()[1].function)

        return (u, expected_values)

    @staticmethod
    def _cleanup(u, library_filter):
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            if library_filter not in lib.name:
                continue
            all_jobs = u.dbProvider.get_all_jobs_for_library(lib, JOBTYPE.COMMITALERT)
            for job in all_jobs:
                if job.type != JOBTYPE.COMMITALERT:
                    continue
                u.dbProvider.delete_job(job_id=job.id)

    def _check_job(self, job, expected_values, outcome=None):
        self.assertEqual(job.type, JOBTYPE.COMMITALERT)
        self.assertEqual(job.version, expected_values.new_version_id())
        self.assertEqual(job.status, JOBSTATUS.DONE)
        self.assertEqual(job.outcome, outcome if outcome else JOBOUTCOME.ALL_SUCCESS)
        self.assertEqual(job.bugzilla_id, expected_values.get_filed_bug_id_func())

    @logEntryExit
    def testNoAlert(self):
        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            lambda: COMMITS_MAIN[0],  # current_library_version_func
            lambda: "",  # new_library_version_func
            lambda: 0,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: {},  # filed_bug_ids_func
            library_filter)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 0, "I shouldn't have created a commit-alert job, but it seems like I have.")

        TestFunctionality._cleanup(u, library_filter)
        # end testNoAlert ----------------------------------------

    @logEntryExit
    def testSimpleAlert(self):
        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            lambda: COMMITS_MAIN[1],  # current_library_version_func
            lambda: COMMITS_MAIN[0],  # new_library_version_func
            lambda: 1,  # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: {},  # filed_bug_ids_func
            library_filter)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testSimpleAlert ----------------------------------------

    @logEntryExit
    def testSimpleAlertOnBranch(self):
        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            lambda: COMMITS_BRANCH1[1],  # current_library_version_func
            lambda: COMMITS_BRANCH1[0],  # new_library_version_func
            lambda: 1,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: {},  # filed_bug_ids_func
            library_filter,
            branch="somebranch")
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testSimpleAlertOnBranch ----------------------------------------

    @logEntryExit
    def testSimpleAlertAcrossBranch(self):
        """
        This test starts us on a commit off the branch and we move onto the branch.
        """
        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            lambda: COMMITS_MAIN[0],  # current_library_version_func
            lambda: COMMITS_BRANCH1[0],  # new_library_version_func
            lambda: 2,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: {},  # filed_bug_ids_func
            library_filter,
            branch="somebranch")
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testSimpleAlertAcrossBranch ----------------------------------------

    @logEntryExit
    def testTwoSimpleAlerts(self):
        call_counter = 0

        def get_current_lib_revision():
            if call_counter == 0:
                return COMMITS_MAIN[2]
            return COMMITS_MAIN[1]

        def get_next_lib_revision():
            if call_counter == 0:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def get_lib_repo():
            if call_counter == 0:
                return "test-repo-%s.bundle" % COMMITS_MAIN[1]
            return "test-repo-%s.bundle" % COMMITS_MAIN[0]

        expected_commits_seen = functools.partial(GENERIC_EXPECTED_COMMITS_SEEN, get_next_lib_revision, get_current_lib_revision)

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            return 51

        def expected_bugs_that_have_been_filed(only_open):
            if call_counter == 0:
                return []
            if call_counter == 1:
                return [50]
            return [50, 51]

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            repo_func=get_lib_repo)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        call_counter += 1

        # Run it again, we should create another job.
        u.run(library_filter=library_filter)

        # The most recently created job has moved to the first slot in the array
        all_jobs = u.dbProvider.get_all_jobs()

        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should have created two jobs.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testTwoSimpleAlerts ----------------------------------------

    @logEntryExit
    def testTwoSimpleAlertsSkip2(self):
        call_counter = 0

        def get_current_lib_revision():
            if call_counter == 0:
                return COMMITS_MAIN[4]
            return COMMITS_MAIN[1]

        def get_next_lib_revision():
            if call_counter == 0:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def get_lib_repo():
            if call_counter == 0:
                return "test-repo-%s.bundle" % COMMITS_MAIN[1]
            return "test-repo-%s.bundle" % COMMITS_MAIN[0]

        expected_commits_seen = functools.partial(GENERIC_EXPECTED_COMMITS_SEEN, get_next_lib_revision, get_current_lib_revision)

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            return 51

        def expected_bugs_that_have_been_filed(only_open):
            if call_counter == 0:
                return []
            elif call_counter == 1:
                return [50]
            return [50, 51]

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            repo_func=get_lib_repo)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        call_counter += 1

        # Run it again, we should create another job.
        u.run(library_filter=library_filter)

        # The most recently created job has moved to the first slot in the array
        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should have created two jobs.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testTwoSimpleAlertsSkip2 ----------------------------------------

    @logEntryExit
    def testTwoSimpleAlertsTimeLagged(self):
        call_counter = 0

        def get_current_lib_revision():
            if call_counter < 2:
                return COMMITS_MAIN[2]
            return COMMITS_MAIN[1]

        def get_next_lib_revision():
            if call_counter < 2:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def get_lib_repo():
            if call_counter < 2:
                return "test-repo-%s.bundle" % COMMITS_MAIN[1]
            return "test-repo-%s.bundle" % COMMITS_MAIN[0]

        expected_commits_seen = functools.partial(GENERIC_EXPECTED_COMMITS_SEEN, get_next_lib_revision, get_current_lib_revision)

        def get_filed_bug_id():
            if call_counter < 2:
                return 50
            return 51

        def expected_bugs_that_have_been_filed(only_open):
            if call_counter == 0:
                return []
            elif call_counter in [1, 2]:
                return [50]
            return [50, 51]

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            repo_func=get_lib_repo)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        call_counter += 1

        # Run it again, we shouldn't do anything new.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should not have created a new job.")

        call_counter += 1

        # Run it a third time, and now we should create another job.
        u.run(library_filter=library_filter)

        # The most recently created job has moved to the first slot in the array
        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should have created two jobs.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testTwoSimpleAlertsTimeLagged ----------------------------------------

    @logEntryExit
    def testTwoAlertsNewCommitsNoUpdate(self):
        call_counter = 0

        def get_current_lib_revision():
            return COMMITS_MAIN[2]

        def get_next_lib_revision():
            if call_counter < 2:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def get_lib_repo():
            if call_counter < 2:
                return "test-repo-%s.bundle" % COMMITS_MAIN[1]
            return "test-repo-%s.bundle" % COMMITS_MAIN[0]

        # They are ordered newest to oldest, so we need to invert the number
        def expected_commits_seen():
            if call_counter < 2:
                return 1
            return 1

        def get_filed_bug_id():
            if call_counter < 2:
                return 50
            return 51

        def expected_bugs_that_have_been_filed(only_open):
            if call_counter == 0:
                return []
            elif call_counter in [1, 2]:
                return [50]
            return [50, 51]

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            repo_func=get_lib_repo)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        call_counter += 1

        # Run it again, we shouldn't do anything new.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should not have created a new job.")

        call_counter += 1

        # Run it a third time, and now we should create another job.
        u.run(library_filter=library_filter)

        # The most recently created job has moved to the first slot in the array
        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should have created two jobs.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testTwoAlertsNewCommitsNoUpdate ----------------------------------------

    @logEntryExit
    def testAlertAcrossFFVersions(self):
        call_counter = 0

        def filed_bug_ids(only_open):
            if call_counter == 0:
                return []
            return [5]

        global was_marked_affected
        was_marked_affected = False

        def assert_affected(bug_id, ff_version, affected):
            global was_marked_affected
            was_marked_affected = True
            affected_str = "affected" if affected else "unaffected"
            assert affected, "Marked %s as %s for %s when we shouldn't have." % (bug_id, affected_str, ff_version)

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            lambda: COMMITS_MAIN[1],  # current_library_version_func
            lambda: COMMITS_MAIN[0],  # new_library_version_func
            lambda: 1,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            filed_bug_ids,
            library_filter,
            assert_affected_func=assert_affected,
            keep_tmp_db=True)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)
        self.assertFalse(was_marked_affected)

        old_ff_version = u.config_dictionary['General']['ff-version']

        config_dictionary = copy.deepcopy(u.config_dictionary)
        config_dictionary['Database']['keep_tmp_db'] = False
        config_dictionary['General']['ff-version'] += 1
        config_dictionary['General']['repo'] = "https://hg.mozilla.org/mozilla-beta"

        call_counter += 1

        u = Updatebot(config_dictionary, PROVIDERS)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should still have one job.")
        self._check_job(all_jobs[0], expected_values)
        self.assertEqual(all_jobs[0].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the bug")
        self.assertTrue(was_marked_affected)

        TestFunctionality._cleanup(u, library_filter)
        # end testAlertAcrossFFVersions ----------------------------------------

    @logEntryExit
    def testTwoAlertsBumpFF(self):
        """
        This test creates two alerts, bumps Firefox, and then asserts that the new FF is marked
        on both bugs.  It also asserts that the second bug references the first in the comments.
        """
        call_counter = 0

        def get_current_lib_revision():
            return COMMITS_MAIN[2]

        def get_next_lib_revision():
            if call_counter < 1:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def get_lib_repo():
            if call_counter < 1:
                return "test-repo-%s.bundle" % COMMITS_MAIN[1]
            return "test-repo-%s.bundle" % COMMITS_MAIN[0]

        # They are ordered newest to oldest, so we need to invert the number
        def expected_commits_seen():
            if call_counter < 1:
                return 1
            return 1

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            elif call_counter == 1:
                return 51
            else:
                assert False

        def expected_bugs_that_have_been_filed(only_open):
            if call_counter == 0:
                return []
            elif call_counter == 1:
                return [50]
            return [50, 51]

        global was_marked_affected
        was_marked_affected = False

        def assert_affected(bug_id, ff_version, affected):
            global was_marked_affected
            was_marked_affected = True
            affected_str = "affected" if affected else "unaffected"
            assert affected, "Marked %s as %s for %s when we shouldn't have." % (bug_id, affected_str, ff_version)

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            assert_affected_func=assert_affected,
            repo_func=get_lib_repo,
            keep_tmp_db=True)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)
        self.assertFalse(was_marked_affected)

        call_counter += 1

        # Run it again, and now we should create another job.
        u.run(library_filter=library_filter)

        # The most recently created job has moved to the first slot in the array
        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should have created two jobs.")
        self._check_job(all_jobs[0], expected_values)
        self.assertFalse(was_marked_affected)

        # Now bump the Firefox Version
        old_ff_version = u.config_dictionary['General']['ff-version']

        config_dictionary = copy.deepcopy(u.config_dictionary)
        config_dictionary['Database']['keep_tmp_db'] = False
        config_dictionary['General']['ff-version'] += 1
        config_dictionary['General']['repo'] = "https://hg.mozilla.org/mozilla-beta"

        call_counter += 1

        u = Updatebot(config_dictionary, PROVIDERS)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should still have two jobs.")
        self.assertEqual(all_jobs[0].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the second bug")
        self.assertEqual(all_jobs[1].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the first bug")
        self.assertTrue(was_marked_affected)

        TestFunctionality._cleanup(u, library_filter)
        # end testTwoAlertsNewCommitsNoUpdate ----------------------------------------

    @logEntryExit
    def testOneAlertCloseItAnotherAlertBumpFF(self):
        """
        This test creates one alert, then closes it. Then we create a second alert and confirm that
        it doesn't reference the first. Then we Bump FF and confirm it only edits the second alert.
        """
        call_counter = 0

        def get_current_lib_revision():
            return COMMITS_MAIN[2]

        def get_next_lib_revision():
            if call_counter < 1:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def get_lib_repo():
            if call_counter < 1:
                return "test-repo-%s.bundle" % COMMITS_MAIN[1]
            return "test-repo-%s.bundle" % COMMITS_MAIN[0]

        # They are ordered newest to oldest, so we need to invert the number
        def expected_commits_seen():
            if call_counter < 1:
                return 1
            return 1

        def get_filed_bug_id():
            if call_counter == 0:
                return 50
            elif call_counter == 1:
                return 51
            else:
                assert False

        def expected_bugs_that_have_been_filed(only_open):
            if call_counter == 0:
                return []
            if call_counter == 1 and only_open:
                return []
            if call_counter == 1:
                return [50]
            if call_counter > 1 and only_open:
                return [51]
            if call_counter > 1:
                return [50, 51]

        def assert_affected(bug_id, ff_version, affected):
            affected_str = "affected" if affected else "unaffected"
            assert affected, "Marked %s as %s for %s when we shouldn't have." % (bug_id, affected_str, ff_version)

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            assert_affected_func=assert_affected,
            repo_func=get_lib_repo,
            keep_tmp_db=True)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        # Now we bump and this implictly closes the first bug via expected_bugs_that_have_been_filed
        call_counter += 1

        # Run it again, and now we should create another job.
        u.run(library_filter=library_filter)

        # The most recently created job has moved to the first slot in the array
        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should have created two jobs.")
        self._check_job(all_jobs[0], expected_values)

        # Now bump the Firefox Version
        old_ff_version = u.config_dictionary['General']['ff-version']

        config_dictionary = copy.deepcopy(u.config_dictionary)
        config_dictionary['Database']['keep_tmp_db'] = False
        config_dictionary['General']['ff-version'] += 1
        config_dictionary['General']['repo'] = "https://hg.mozilla.org/mozilla-beta"

        call_counter += 1

        u = Updatebot(config_dictionary, PROVIDERS)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 2, "I should still have two jobs.")
        self.assertEqual(all_jobs[0].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the second bug")
        self.assertEqual(all_jobs[1].ff_versions, set([old_ff_version]), "I did add the second Firefox version to the first bug but shouldn't have")

        TestFunctionality._cleanup(u, library_filter)
        # end testOneAlertCloseItAnotherAlertBumpFF ----------------------------------------

    @logEntryExit
    def testUnaffectedVersion(self):
        """
        In this test, we file a bug, and then bump the FF version. On the new version, we tell it is
        not affected by returning the 'new' version as the 'current' version. This simulates it not
        being affected; and we assert that we marked the old bug as unaffected.

        Note this isn't a perfect test, because really we expect to mark things as 'unaffected' not
        because we update a library before Updatebot runs for the first time on a new FF version; but
        because in FF Version n+1 we change to a new upstream branch, and we need to mark the old bugs
        on a different branch as unaffected for the new FF version.
        """
        call_counter = 0

        def current_library_version():
            if call_counter == 0:
                return COMMITS_MAIN[1]
            return COMMITS_MAIN[0]

        def new_library_version():
            return COMMITS_MAIN[0]

        def filed_bug_ids(only_open):
            if call_counter == 0:
                return []
            return [5]

        def assert_affected(bug_id, ff_version, affected):
            affected_str = "affected" if affected else "unaffected"
            assert not affected, "Marked %s as %s for %s when we shouldn't have." % (bug_id, affected_str, ff_version)

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            current_library_version,
            new_library_version,
            lambda: 1,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            filed_bug_ids,
            library_filter,
            assert_affected_func=assert_affected,
            keep_tmp_db=True)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        old_ff_version = u.config_dictionary['General']['ff-version']

        config_dictionary = copy.deepcopy(u.config_dictionary)
        config_dictionary['Database']['keep_tmp_db'] = False
        config_dictionary['General']['ff-version'] += 1
        config_dictionary['General']['repo'] = "https://hg.mozilla.org/mozilla-beta"

        call_counter += 1

        u = Updatebot(config_dictionary, PROVIDERS)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should still have one job.")
        self._check_job(all_jobs[0], expected_values)
        self.assertEqual(all_jobs[0].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the bug")

        TestFunctionality._cleanup(u, library_filter)
        # end testUnaffectedVersion ----------------------------------------


if __name__ == '__main__':
    unittest.main(verbosity=0)
