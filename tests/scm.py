#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import copy
import unittest

sys.path.append(".")
sys.path.append("..")
from components.scmprovider import SCMProvider
from components.logging import SimpleLogger, log
from components.commandprovider import CommandProvider

from tests.mock_repository import default_test_repo, test_repo_path_wrapper, COMMITS_MAIN

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)

# 0 index is newest, make a reverse copy
COMMITS_MAIN_R = copy.deepcopy(COMMITS_MAIN)
COMMITS_MAIN_R.reverse()


class TestCommandRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loggingProvider = SimpleLogger(localconfig['Logging'])

        real_command_runner = CommandProvider({})
        real_command_runner.update_config({
            'LoggingProvider': loggingProvider
        })

        cls.scmProvider = SCMProvider({})
        cls.scmProvider.update_config({
            'CommandProvider': real_command_runner,
            'LoggingProvider': loggingProvider
        })

        repo_url = test_repo_path_wrapper(default_test_repo())

        cls.scmProvider.initialize()
        cls.scmProvider._ensure_checkout(repo_url)

    @classmethod
    def tearDownClass(cls):
        cls.scmProvider.reset()

    def testCommitsBetween(self):
        # Test a full commits between test
        commits = self.scmProvider._commits_between(COMMITS_MAIN[-1], COMMITS_MAIN[0])
        for i in range(len(commits)):
            self.assertEqual(commits[i].revision, COMMITS_MAIN_R[i + 1])

        # Test rev1 == rev2
        commits = self.scmProvider._commits_between(COMMITS_MAIN[0], COMMITS_MAIN[0])
        self.assertEqual(len(commits), 0)

        # Test rev1 = rev2^
        commits = self.scmProvider._commits_between(COMMITS_MAIN[1], COMMITS_MAIN[0])
        self.assertEqual(commits[0].revision, COMMITS_MAIN[0])


if __name__ == '__main__':
    unittest.main(verbosity=0)
