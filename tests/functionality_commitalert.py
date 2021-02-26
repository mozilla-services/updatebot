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


def DEFAULT_EXPECTED_VALUES(commithash):
    return Struct(**{
        'library_version_id': "newcommit_" + commithash,
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
        pass

    def file_bug(self, library, summary, description, cc, see_also=None):
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
        real_command_runner = CommandProvider({})
        real_command_runner.update_config({
            'LoggingProvider': SimpleLogger(localconfig['Logging'])
        })

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
            'Bugzilla': {'filed_bug_id': None},
            'Mercurial': {},
            'Taskcluster': {},
            'Phabricator': {},
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

        expected_values = DEFAULT_EXPECTED_VALUES(try_revision)
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
        (u, expected_values) = TestFunctionality._setup("ABVDEF", library_filter)
        u.run(library_filter=library_filter)

        all_jobs = u.dbProvider.get_all_jobs()
        self.assertEqual(len([j for j in all_jobs if j.library_shortname != "dav1d"]), 0, "I shouldn't have created a commit-alert job, but it seems like I have.")


if __name__ == '__main__':
    unittest.main(verbosity=0)
