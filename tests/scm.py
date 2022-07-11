#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import copy
import unittest

sys.path.append(".")
sys.path.append("..")
from components.scmprovider import SCMProvider
from components.logging import SimpleLogger
from components.commandprovider import CommandProvider

try:
    from localconfig import localconfig
except ImportError:
    log("Unit tests require a local database configuration to be defined.")
    sys.exit(1)

# 0 index is newest
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

# 0 index is oldest
REPO_COMMITS_R = copy.deepcopy(REPO_COMMITS)
REPO_COMMITS_R.reverse()


def path_wrapper(p):
    return os.path.join(os.getcwd(), "tests/" if not os.getcwd().endswith("tests") else "", p)

class TestCommandRunner(unittest.TestCase):
    def test(self):
        loggingProvider = SimpleLogger(localconfig['Logging'])

        real_command_runner = CommandProvider({})
        real_command_runner.update_config({
            'LoggingProvider': loggingProvider
        })

        scmProvider = SCMProvider({})
        scmProvider.update_config({
            'CommandProvider': real_command_runner,
            'LoggingProvider': loggingProvider
            })


        repo_url = path_wrapper("test-repo.bundle")

        scmProvider.initialize()
        scmProvider._ensure_checkout(repo_url)

        # Test a full commits between test
        commits = scmProvider._commits_between(REPO_COMMITS[-1], REPO_COMMITS[0])
        for i in range(len(commits)):
            self.assertEqual(commits[i].revision, REPO_COMMITS_R[i+1])

        # Test rev1 == rev2
        commits = scmProvider._commits_between(REPO_COMMITS[0], REPO_COMMITS[0])
        self.assertEqual(len(commits), 0)

        # Test rev1 = rev2^
        commits = scmProvider._commits_between(REPO_COMMITS[1], REPO_COMMITS[0])
        self.assertEqual(commits[0].revision, REPO_COMMITS[0])

        scmProvider.reset()


if __name__ == '__main__':
    unittest.main(verbosity=0)

