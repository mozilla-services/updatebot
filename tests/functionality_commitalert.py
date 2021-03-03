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


def DEFAULT_EXPECTED_VALUES(new_library_version):
    return Struct(**{
        'new_version_id': new_library_version,
        'filed_bug_id': 50,
        'ff_version': 87
    })


def COMMAND_MAPPINGS(expected_values):
    return {
        "git": DO_EXECUTE
    }


class MockedBugzillaProvider(BaseProvider):
    def __init__(self, config):
        self._filed_bug_id = config['filed_bug_id']
        self._expected_commits_seen = config['expected_commits_seen']
        pass

    def file_bug(self, library, summary, description, cc, see_also=None):
        assert str(self._expected_commits_seen) + " new commits" in summary, \
            "We did not see the expected number of commits in the bug we filed. Expected %s, summary is '%s'" % (self._expected_commits_seen, summary)

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
    def _setup(current_library_version, new_library_version, library_filter, branch="master"):
        real_command_runner = CommandProvider({})
        real_command_runner.update_config({
            'LoggingProvider': SimpleLogger(localconfig['Logging'])
        })

        # We use this to determine how many commits we expect to find, which lets us validate
        # we saw the correct number (in the bugzillaprovider)
        repo_commits = [
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
        expected_commits_seen = \
            - (repo_commits.index(new_library_version) - repo_commits.index(current_library_version)) if new_library_version else 0

        db_config = transform_db_config_to_tmp_db(localconfig['Database'])
        configs = {
            'General': {
                'env': 'dev',
                'gecko-path': '.',
                'ff-version': None
            },
            'Command': {
                'test_mappings': None,
                'real_runner': real_command_runner
            },
            'Logging': localconfig['Logging'],
            'Database': db_config,
            'Vendor': {},
            'Bugzilla': {
                'filed_bug_id': None,
                'expected_commits_seen': expected_commits_seen
            },
            'Mercurial': {},
            'Taskcluster': {},
            'Phabricator': {},
            'Library': {
                'commitalert_revision_override': current_library_version,
                'commitalert_branch_override': branch
            }
        }

        providers = {
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

        expected_values = DEFAULT_EXPECTED_VALUES(new_library_version)
        configs['General']['ff-version'] = expected_values.ff_version
        configs['Bugzilla']['filed_bug_id'] = expected_values.filed_bug_id
        configs['Command']['test_mappings'] = COMMAND_MAPPINGS(expected_values)

        u = Updatebot(configs, providers)

        # Ensure we don't have a dirty database with existing jobs
        tc = unittest.TestCase()
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            j = u.dbProvider.get_job(lib, expected_values.new_version_id)
            tc.assertEqual(j, None, "When running %s, we found an existing job, indicating the database is dirty and should be cleaned." % inspect.stack()[1].function)

        return (u, expected_values)

    @staticmethod
    def _cleanup(u, library_filter):
        for lib in u.libraryProvider.get_libraries(u.config_dictionary['General']['gecko-path']):
            if library_filter not in lib.name:
                continue
            all_jobs = u.dbProvider.get_all_jobs_for_library(lib)
            for job in all_jobs:
                if job.type != JOBTYPE.COMMITALERT:
                    continue
                u.dbProvider.delete_job(job_id=job.id)

    def _check_job(self, job, expected_values):
        self.assertEqual(job.type, JOBTYPE.COMMITALERT)
        self.assertEqual(job.ff_version, expected_values.ff_version)
        self.assertEqual(job.version, expected_values.new_version_id)
        self.assertEqual(job.status, JOBSTATUS.DONE)
        self.assertEqual(job.outcome, JOBOUTCOME.ALL_SUCCESS)
        self.assertEqual(job.bugzilla_id, expected_values.filed_bug_id)

    @logEntryExit
    def testNoAlert(self):
        library_filter = "aom"
        (u, expected_values) = TestFunctionality._setup(
            "11c85fb14571c822e5f7f8b92a7e87749430b696",
            "",
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
            "0886ba657dedc54fad06018618cc07689198abea",
            "11c85fb14571c822e5f7f8b92a7e87749430b696",
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
            "b6972c67b63be20a4b28ed246fd06f6173265bb5",
            "edc676dbd57fd75c6e37dfb8ce616a792fffa8a9",
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
            "11c85fb14571c822e5f7f8b92a7e87749430b696",
            "edc676dbd57fd75c6e37dfb8ce616a792fffa8a9",
            library_filter,
            branch="somebranch")
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 1, "I should have created a single job.")
        self._check_job(all_jobs[0], expected_values)

        TestFunctionality._cleanup(u, library_filter)
        # end testSimpleAlertAcrossBranch ----------------------------------------


if __name__ == '__main__':
    unittest.main(verbosity=0)
