#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import copy
import inspect
import unittest
import functools

from http import server
from threading import Thread

sys.path.append(".")
sys.path.append("..")
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
from tests.mock_treeherder_server import MockTreeherderServer
from tests.database import transform_db_config_to_tmp_db

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)

"""
For this file, we have test-repo.bundle which contains the below commits.

We also have bundles that culminate in each of the revisions, for use when
the library 'updates upstream'.

Note: if you are create a test repo bundle, if all you do is
   git bundle create repo-file.bundle master
When you clone it, it will fail with the error
   remote HEAD refers to nonexistent ref, unable to checkout
To resolve this, you need to create it this way:
    git bundle create repo-file.bundle HEAD master

HOWEVER that is only when you are creating a bundle with one branch. If you
are creating a bundle with multiple branches; then you should do
    git bundle create test-repo.bundle HEAD --all
If you specify both -all and master you will get the error
    fatal: multiple updates for ref 'refs/remotes/origin/master' not allowed

edc676dbd57fd75c6e37dfb8ce616a792fffa8a9  (HEAD -> somebranch) Add functionality
b6972c67b63be20a4b28ed246fd06f6173265bb5  Skeleton for some functionality
11c85fb14571c822e5f7f8b92a7e87749430b696  (origin/master, origin/HEAD, master) Maybe just remove this function completely
0886ba657dedc54fad06018618cc07689198abea  Update readme for CVE-2021-1
fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830  Rename file
f80c792e9a279cab9abedf7f3a8f4e41deaef649  Fix a potential bufer overflow
b321ea35eb25874e1531c87ed53e03bb81f7693b  Utility function for printing strings
7c9e119ef8d30f4c938f6337ad1715732ac1b023  main() should ahve arguments
3b0c38accbfc542f3f75ab21227c18ad554570c4  Add main.c
9dd7270d76d9e63a4ada40d358dd0e4505d16ab3  Add README file
"""

# We use this to determine how many commits we expect to find, which lets us validate
# we saw the correct number (in the bugzillaprovider)
REPO_COMMITS = [
    "edc676dbd57fd75c6e37dfb8ce616a792fffa8a9",
    "b6972c67b63be20a4b28ed246fd06f6173265bb5",
    "11c85fb14571c822e5f7f8b92a7e87749430b696",
    "0886ba657dedc54fad06018618cc07689198abea",
    "fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830",
    "f80c792e9a279cab9abedf7f3a8f4e41deaef649",
    "b321ea35eb25874e1531c87ed53e03bb81f7693b",
    "7c9e119ef8d30f4c938f6337ad1715732ac1b023",
    "3b0c38accbfc542f3f75ab21227c18ad554570c4",
    "9dd7270d76d9e63a4ada40d358dd0e4505d16ab3",
]

# They are ordered newest to oldest, so we need to invert the number


def GENERIC_EXPECTED_COMMITS_SEEN(get_next_lib_revision, get_current_lib_revision):
    return - (REPO_COMMITS.index(get_next_lib_revision()) - REPO_COMMITS.index(get_current_lib_revision())) if get_next_lib_revision() else 0


def DEFAULT_EXPECTED_VALUES(new_library_version_func, get_filed_bug_id_func):
    return Struct(**{
        'new_version_id': new_library_version_func,
        'get_filed_bug_id_func': get_filed_bug_id_func,
    })


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

    def file_bug(self, library, summary, description, cc_list, needinfo=None, see_also=None, depends_on=None, moco_confidential=False):
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

    def dupe_bug(self, bug_id, comment, dupe_id):
        pass

    def find_open_bugs(self, bug_ids):
        return self._filed_bug_ids_func(ONLY_OPEN)

    def mark_ff_version_affected(self, bug_id, ff_version, affected):
        pass


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
    def _setup(current_library_version_func,
               new_library_version_func,
               expected_commits_seen_func,
               get_filed_bug_id_func,
               filed_bug_ids_func,
               library_filter,
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
                'filed_bug_ids_func': filed_bug_ids_func
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
            lambda: "11c85fb14571c822e5f7f8b92a7e87749430b696",  # current_library_version_func
            lambda: "",  # new_library_version_func
            lambda: 0,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: [],  # filed_bug_ids_func
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
            lambda: "0886ba657dedc54fad06018618cc07689198abea",  # current_library_version_func
            lambda: "11c85fb14571c822e5f7f8b92a7e87749430b696",  # new_library_version_func
            lambda: 1,  # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: [],  # filed_bug_ids_func
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
            lambda: "b6972c67b63be20a4b28ed246fd06f6173265bb5",  # current_library_version_func
            lambda: "edc676dbd57fd75c6e37dfb8ce616a792fffa8a9",  # new_library_version_func
            lambda: 1,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: [],  # filed_bug_ids_func
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
            lambda: "11c85fb14571c822e5f7f8b92a7e87749430b696",  # current_library_version_func
            lambda: "edc676dbd57fd75c6e37dfb8ce616a792fffa8a9",  # new_library_version_func
            lambda: 2,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            lambda x: [],  # filed_bug_ids_func
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
                return "fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830"
            return "0886ba657dedc54fad06018618cc07689198abea"

        def get_next_lib_revision():
            if call_counter == 0:
                return "0886ba657dedc54fad06018618cc07689198abea"
            return "11c85fb14571c822e5f7f8b92a7e87749430b696"

        def get_lib_repo():
            if call_counter == 0:
                return "test-repo-0886ba657dedc54fad06018618cc07689198abea.bundle"
            return "test-repo-11c85fb14571c822e5f7f8b92a7e87749430b696.bundle"

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
                return "b321ea35eb25874e1531c87ed53e03bb81f7693b"
            return "0886ba657dedc54fad06018618cc07689198abea"

        def get_next_lib_revision():
            if call_counter == 0:
                return "0886ba657dedc54fad06018618cc07689198abea"
            return "11c85fb14571c822e5f7f8b92a7e87749430b696"

        def get_lib_repo():
            if call_counter == 0:
                return "test-repo-0886ba657dedc54fad06018618cc07689198abea.bundle"
            return "test-repo-11c85fb14571c822e5f7f8b92a7e87749430b696.bundle"

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
                return "fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830"
            return "0886ba657dedc54fad06018618cc07689198abea"

        def get_next_lib_revision():
            if call_counter < 2:
                return "0886ba657dedc54fad06018618cc07689198abea"
            return "11c85fb14571c822e5f7f8b92a7e87749430b696"

        def get_lib_repo():
            if call_counter < 2:
                return "test-repo-0886ba657dedc54fad06018618cc07689198abea.bundle"
            return "test-repo-11c85fb14571c822e5f7f8b92a7e87749430b696.bundle"

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
            return "fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830"

        def get_next_lib_revision():
            if call_counter < 2:
                return "0886ba657dedc54fad06018618cc07689198abea"
            return "11c85fb14571c822e5f7f8b92a7e87749430b696"

        def get_lib_repo():
            if call_counter < 2:
                return "test-repo-0886ba657dedc54fad06018618cc07689198abea.bundle"
            return "test-repo-11c85fb14571c822e5f7f8b92a7e87749430b696.bundle"

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

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            lambda: "0886ba657dedc54fad06018618cc07689198abea",  # current_library_version_func
            lambda: "11c85fb14571c822e5f7f8b92a7e87749430b696",  # new_library_version_func
            lambda: 1,   # expected_commits_seen_func
            lambda: 5,   # get_filed_bug_id_func,
            filed_bug_ids,
            library_filter,
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
        # end testAlertAcrossFFVersions ----------------------------------------

    @logEntryExit
    def testTwoAlertsBumpFF(self):
        """
        This test creates two alerts, bumps Firefox, and then asserts that the new FF is marked
        on both bugs.  It also asserts that the second bug references the first in the comments.
        """
        call_counter = 0

        def get_current_lib_revision():
            return "fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830"

        def get_next_lib_revision():
            if call_counter < 1:
                return "0886ba657dedc54fad06018618cc07689198abea"
            return "11c85fb14571c822e5f7f8b92a7e87749430b696"

        def get_lib_repo():
            if call_counter < 1:
                return "test-repo-0886ba657dedc54fad06018618cc07689198abea.bundle"
            return "test-repo-11c85fb14571c822e5f7f8b92a7e87749430b696.bundle"

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

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
            repo_func=get_lib_repo,
            keep_tmp_db=True)

        # Run it once. We should create a job.
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

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
        self.assertEqual(all_jobs[1].ff_versions, set([old_ff_version + 1, old_ff_version]), "I did not add the second Firefox version to the first bug")

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
            return "fb4216ff88bdfbe73617b8c5ebeb9da07a3cf830"

        def get_next_lib_revision():
            if call_counter < 1:
                return "0886ba657dedc54fad06018618cc07689198abea"
            return "11c85fb14571c822e5f7f8b92a7e87749430b696"

        def get_lib_repo():
            if call_counter < 1:
                return "test-repo-0886ba657dedc54fad06018618cc07689198abea.bundle"
            return "test-repo-11c85fb14571c822e5f7f8b92a7e87749430b696.bundle"

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

        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            get_current_lib_revision,
            get_next_lib_revision,
            expected_commits_seen,
            get_filed_bug_id,
            expected_bugs_that_have_been_filed,
            library_filter,
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


if __name__ == '__main__':
    unittest.main(verbosity=0)
