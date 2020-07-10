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

TRY_OUTPUT = """
Test configuration changed. Regenerating backend.
Creating temporary commit for remote...
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
remote:   https://hg.mozilla.org/try/rev/e152bb86666565ee6619c15f60156cd6c79580a9
remote:
remote: Follow the progress of your build on Treeherder:
remote:   https://treeherder.mozilla.org/#/jobs?repo=try&revision=e152bb86666565ee6619c15f60156cd6c79580a9
remote: recorded changegroup in replication log in 0.011s
push complete
temporary commit removed, repository restored
"""

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
-> https://phabricator.services.mozilla.com/D83119
"""

ExpectedValues = Struct(**{
    'library_version_id': "newversion",
    'filed_bug_id': 50,
    'try_revision_id': "e152bb86666565ee6619c15f60156cd6c79580a9",
    'phab_revision': 83119
})


class TestConfigVendorProvider(VendorProvider):
    def __init__(self, config):
        super(VendorProvider, self).__init__(config)

    def check_for_update(self, library):
        return ExpectedValues.library_version_id


class TestConfigBugzillaProvider(BaseProvider):
    def __init__(self, config):
        pass

    def file_bug(self, library, new_release_version):
        return ExpectedValues.filed_bug_id

    def comment_on_bug(self, bug_id, status, try_run=None):
        pass


class TestConfigTaskclusterProvider(BaseProvider):
    def __init__(self, config):
        pass


COMMAND_MAPPINGS = {
    "./mach vendor": ExpectedValues.library_version_id,
    "./mach try fuzzy": TRY_OUTPUT,
    "arc diff --verbatim": ARC_OUTPUT
}


class TestCommandRunner(unittest.TestCase):
    def testFunctionalityWithRealDatabase(self):
        configs = {
            'General': {'env': 'dev'},
            'Command': {'test_mappings': COMMAND_MAPPINGS},
            'Logging': localconfig['Logging'],
            'Database': localconfig['Database'],
            'Vendor': {},
            'Bugzilla': {},
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

            # Not Mocked At All
            'Vendor': VendorProvider,

            # Fully Mocked
            'Bugzilla': TestConfigBugzillaProvider,

            # Not Mocked At All
            'Mercurial': MercurialProvider,

            # Not Mocked At All
            'Taskcluster': TaskclusterProvider,

            # Not Mocked At All
            'Phabricator': PhabricatorProvider,
        }
        u = Updatebot(configs, providers)
        u.run()

        # Check For Success
        for l in u.dbProvider.get_libraries():
            j = u.dbProvider.get_job(l, ExpectedValues.library_version_id)

            self.assertNotEqual(j, None)
            self.assertEqual(l.shortname, j.library_shortname)
            self.assertEqual(ExpectedValues.library_version_id, j.version)
            self.assertEqual(JOBSTATUS.AWAITING_TRY_RESULTS, j.status)
            self.assertEqual(ExpectedValues.filed_bug_id, j.bugzilla_id)
            self.assertEqual(ExpectedValues.phab_revision, j.phab_revision)
            self.assertEqual(
                ExpectedValues.try_revision_id, j.try_revision)

        # Cleanup
        for l in u.dbProvider.get_libraries():
            u.dbProvider.delete_job(l, ExpectedValues.library_version_id)


if __name__ == '__main__':
    unittest.main()
