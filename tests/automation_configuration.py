#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append("..")
import unittest

from automation import Updatebot

class BaseTestConfigProvider:
    def __init__(self, config):
        assert('specialkey' in config)
        assert(self.expected == config['specialkey'])

class TestConfigDatabaseProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'database!'
        super(TestConfigDatabaseProvider, self).__init__(config)

class TestConfigVendorProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'vendor!'
        super(TestConfigVendorProvider, self).__init__(config)

class TestConfigBugzillaProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'bugzilla!'
        super(TestConfigBugzillaProvider, self).__init__(config)

class TestConfigMercurialProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'mercurial!'
        super(TestConfigMercurialProvider, self).__init__(config)

class TestConfigTaskclusterProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'taskcluster!'
        super(TestConfigTaskclusterProvider, self).__init__(config)

class TestConfigPhabricatorProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'phab!'
        super(TestConfigPhabricatorProvider, self).__init__(config)

class TestCommandRunner(unittest.TestCase):
    def testConfigurationPassing(self):
        configs = {
            'Database': {'specialkey': 'database!'},
            'Vendor': {'specialkey': 'vendor!'},
            'Bugzilla': {'specialkey': 'bugzilla!'},
            'Mercurial': {'specialkey': 'mercurial!'},
            'Taskcluster': {'specialkey': 'taskcluster!'},
            'Phabricator': {'specialkey': 'phab!'},
        }
        providers = {
            'Database': TestConfigDatabaseProvider,
            'Vendor': TestConfigVendorProvider,
            'Bugzilla': TestConfigBugzillaProvider,
            'Mercurial': TestConfigMercurialProvider,
            'Taskcluster': TestConfigTaskclusterProvider,
            'Phabricator': TestConfigPhabricatorProvider,
        }
        u = Updatebot(configs, providers)

if __name__ == '__main__':
    unittest.main()
