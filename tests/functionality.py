#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from automation import Updatebot

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


class TestConfigVendorProvider(VendorProvider):
    def __init__(self, config):
        super(VendorProvider, self).__init__(config)

    def check_for_update(self, library):
        return TestConfigVendorProvider.version_id


TestConfigVendorProvider.version_id = "TestConfigVendorProvider_newversion"


class TestConfigBugzillaProvider(BaseProvider):
    def __init__(self, config):
        pass

    def file_bug(self, library, new_release_version):
        return TestConfigBugzillaProvider.bug_id

    def comment_on_bug(self, bug_id, status, try_run=None):
        pass


TestConfigBugzillaProvider.bug_id = 10


class TestConfigTaskclusterProvider(BaseProvider):
    def __init__(self, config):
        pass


TestConfigTaskclusterProvider.revision_id = "e152bb86666565ee6619c15f60156cd6c79580a9"

COMMAND_MAPPINGS = {
    "./mach vendor": TestConfigVendorProvider.version_id,
    "./mach try fuzzy": TRY_OUTPUT
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
            j = u.dbProvider.get_job(l, TestConfigVendorProvider.version_id)

            self.assertNotEqual(j, None)
            self.assertEqual(l.shortname, j.library_shortname)
            self.assertEqual(TestConfigVendorProvider.version_id, j.version)
            self.assertEqual(JOBSTATUS.AWAITING_TRY_RESULTS, j.status)
            self.assertEqual(TestConfigBugzillaProvider.bug_id, j.bugzilla_id)
            self.assertEqual(
                TestConfigTaskclusterProvider.revision_id, j.try_revision)

        # Cleanup
        for l in u.dbProvider.get_libraries():
            u.dbProvider.delete_job(l, TestConfigVendorProvider.version_id)


if __name__ == '__main__':
    unittest.main()
