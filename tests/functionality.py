#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append("..")
from automation import Updatebot
from components.dbc import DefaultDatabaseProvider
from components.dbmodels import JOBSTATUS

try:
    from localconfig import localconfigs
except ImportError:
    print("Unit tests require a local database configuration to be defined.")
    sys.exit(1)


class TestConfigVendorProvider:
    def __init__(self, config):
        pass

    def check_for_update(self, library):
        return TestConfigVendorProvider.version_id

    def vendor(self, library):
        pass
TestConfigVendorProvider.version_id = "TestConfigVendorProvider_newversion"

class TestConfigBugzillaProvider:
    def __init__(self, config):
        pass

    def file_bug(self, library, new_release_version):
        return TestConfigBugzillaProvider.bug_id

    def comment_on_bug(self, bug_id, status, try_run=None):
        pass
TestConfigBugzillaProvider.bug_id = 10


class TestConfigMercurialProvider:
    def __init__(self, config):
        pass

    def commit(self, library, bug_id, new_release_version):
        pass


class TestConfigTaskclusterProvider:
    def __init__(self, config):
        pass

    def submit_to_try(self, library):
        return TestConfigTaskclusterProvider.revision_id
TestConfigTaskclusterProvider.revision_id = "e152bb86666565ee6619c15f60156cd6c79580a9"

class TestConfigPhabricatorProvider:
    def __init__(self, config):
        pass

    def submit_patch(self):
        pass


class TestCommandRunner(unittest.TestCase):
    def testFunctionalityWithRealDatabase(self):
        configs = {
            'Database': localconfigs['Database'],
            'Vendor': {},
            'Bugzilla': {},
            'Mercurial': {},
            'Taskcluster': {},
            'Phabricator': {},
        }
        providers = {
            'Database': DefaultDatabaseProvider,

            'Vendor': TestConfigVendorProvider,
            'Bugzilla': TestConfigBugzillaProvider,
            'Mercurial': TestConfigMercurialProvider,
            'Taskcluster': TestConfigTaskclusterProvider,
            'Phabricator': TestConfigPhabricatorProvider,
        }
        u = Updatebot(configs, providers)
        u.run()

        # Check For Success
        for l in u.dbProvider.get_libraries():
            j = u.dbProvider.get_job(l, TestConfigVendorProvider.version_id)
            
            self.assertNotEqual(j, None)
            self.assertEqual(l.shortname, j.library_shortname)
            self.assertEqual(TestConfigVendorProvider.version_id, j.version)
            self.assertEqual(JOBSTATUS.SUBMITTED_TRY, j.status)
            self.assertEqual(TestConfigBugzillaProvider.bug_id, j.bugzilla_id)
            self.assertEqual(TestConfigTaskclusterProvider.revision_id, j.try_revision)

        # Cleanup
        for l in u.dbProvider.get_libraries():
            u.dbProvider.delete_job(l, TestConfigVendorProvider.version_id)


if __name__ == '__main__':
    unittest.main()
