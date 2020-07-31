#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from automation import Updatebot

from components.utilities import Struct
from components.providerbase import BaseProvider
from components.logging import LoggingProvider, log
from components.dbc import DatabaseProvider
from components.dbmodels import JOBSTATUS
from components.mach_vendor import VendorProvider
from components.hg import MercurialProvider
from apis.taskcluster import TaskclusterProvider
from apis.phabricator import PhabricatorProvider

from tests.mock_commandprovider import TestCommandProvider

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


def DEFAULT_EXPECTED_VALUES(revision):
    return Struct(**{
        'library_version_id': "newversion_" + revision,
        'filed_bug_id': 50,
        'try_revision_id': revision,
        'phab_revision': 83119
    })


class MockedBugzillaProvider(BaseProvider):
    def __init__(self, config):
        self._filed_bug_id = config['filed_bug_id']
        pass

    def file_bug(self, library, new_release_version):
        return self._filed_bug_id

    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        pass


class TestCommandRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.configs = {
            'General': {'env': 'dev'},
            'Command': {'test_mappings': None},
            'Logging': localconfig['Logging'],
            'Database': localconfig['Database'],
            'Vendor': {},
            'Bugzilla': {'filed_bug_id': None},
            'Mercurial': {},
            'Taskcluster': {},
            'Phabricator': {},
        }
        cls.providers = {
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

            # Not Mocked At All
            'Taskcluster': TaskclusterProvider,

            # Not Mocked At All
            'Phabricator': PhabricatorProvider,
        }

    def testAllNewJobs(self):
        # Setup
        try_revision = "try_rev"  # Doesn't matter
        expected_values = DEFAULT_EXPECTED_VALUES(try_revision)
        self.configs['Bugzilla']['filed_bug_id'] = expected_values.filed_bug_id

        command_mappings = {
            "./mach vendor": expected_values.library_version_id,
            "./mach try auto": TRY_OUTPUT(try_revision),
            "arc diff --verbatim": ARC_OUTPUT
        }
        self.configs['Command']['test_mappings'] = command_mappings

        # Make it
        u = Updatebot(self.configs, self.providers)

        # Ensure we don't have a dirty database with existing jobs
        for l in u.dbProvider.get_libraries():
            j = u.dbProvider.get_job(l, expected_values.library_version_id)
            self.assertEqual(j, None, "When running testAllNewJobs, we found an existing job, indicating the database is dirty and should be cleaned.")

        # Run it
        u.run()

        # Check For Success
        for l in u.dbProvider.get_libraries():
            j = u.dbProvider.get_job(l, expected_values.library_version_id)

            self.assertNotEqual(j, None)
            self.assertEqual(l.shortname, j.library_shortname)
            self.assertEqual(expected_values.library_version_id, j.version)
            self.assertEqual(JOBSTATUS.AWAITING_TRY_RESULTS, j.status)
            self.assertEqual(expected_values.filed_bug_id, j.bugzilla_id)
            self.assertEqual(expected_values.phab_revision, j.phab_revision)
            self.assertEqual(
                expected_values.try_revision_id, j.try_revision)

        # Cleanup
        for l in u.dbProvider.get_libraries():
            u.dbProvider.delete_job(l, expected_values.library_version_id)


if __name__ == '__main__':
    unittest.main()
