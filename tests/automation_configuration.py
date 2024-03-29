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


class BaseTestConfigProvider(BaseProvider):
    def __init__(self, config):
        assert('specialkey' in config)
        assert(self.expected == config['specialkey'])


class TestConfigDatabaseProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'database!'
        super(TestConfigDatabaseProvider, self).__init__(config)

    def check_database(self):
        pass

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigVendorProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'vendor!'
        super(TestConfigVendorProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigBugzillaProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'bugzilla!'
        super(TestConfigBugzillaProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigMercurialProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'mercurial!'
        super(TestConfigMercurialProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigTaskclusterProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'taskcluster!'
        super(TestConfigTaskclusterProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigPhabricatorProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'phab!'
        super(TestConfigPhabricatorProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigLoggingProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'logging!'
        super(TestConfigLoggingProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"

    def log(self, category):
        pass


class TestConfigCommandProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'command!'
        super(TestConfigCommandProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigLibraryProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'library!'
        super(TestConfigLibraryProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestConfigSCMProvider(BaseTestConfigProvider):
    def __init__(self, config):
        self.expected = 'scm!'
        super(TestConfigSCMProvider, self).__init__(config)

    def _update_config(self, config):
        self.also_expected = "Made it!"


class TestCommandRunner(unittest.TestCase):
    def testConfigurationPassing(self):
        configs = {
            'General': {
                'env': 'dev',
                'gecko-path': 'nowhere',
                'ff-version': 87,
                'repo': 'https://hg.mozilla.org/mozilla-central'
            },
            'Database': {'specialkey': 'database!'},
            'Vendor': {'specialkey': 'vendor!'},
            'Bugzilla': {'specialkey': 'bugzilla!'},
            'Mercurial': {'specialkey': 'mercurial!'},
            'Taskcluster': {'specialkey': 'taskcluster!'},
            'Phabricator': {'specialkey': 'phab!'},
            'Command': {'specialkey': 'command!'},
            'Logging': {'specialkey': 'logging!'},
            'Library': {'specialkey': 'library!'},
            'SCM': {'specialkey': 'scm!'},
        }
        providers = {
            'Database': TestConfigDatabaseProvider,
            'Vendor': TestConfigVendorProvider,
            'Bugzilla': TestConfigBugzillaProvider,
            'Mercurial': TestConfigMercurialProvider,
            'Taskcluster': TestConfigTaskclusterProvider,
            'Phabricator': TestConfigPhabricatorProvider,
            'Logging': TestConfigLoggingProvider,
            'Command': TestConfigCommandProvider,
            'Library': TestConfigLibraryProvider,
            'SCM': TestConfigSCMProvider
        }
        u = Updatebot(configs, providers)

        def assert_extra_key(x):
            self.assertTrue("!" in x.also_expected, "Extra key was not populated")

        u.runOnProviders(assert_extra_key)


if __name__ == '__main__':
    unittest.main(verbosity=0)
