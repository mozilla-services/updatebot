#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider
from components.logging import LoggingProvider
from components.utilities import static_vars
from tests.mock_commandprovider import TestCommandProvider
from tests.functionality_utilities import treeherder_response
from tests.mock_treeherder_server import TYPE_HEALTH, TYPE_JOBS


class FakeProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self.f = config['f']


class TestCommandRunner(unittest.TestCase):
    def testInheritance(self):
        config1 = {
            'f': 50
        }

        alice = FakeProvider(config1)

        tcp = TestCommandProvider({})
        lp = LoggingProvider({})
        config2 = {
            'CommandProvider': tcp,
            'LoggingProvider': lp
        }
        alice.update_config(config2)

        self.assertEqual(alice.f, config1['f'], "Did not populate alice.f correctly")
        self.assertEqual(alice.run, tcp.run, "Did not populate alice.run correctly")
        self.assertNotEqual(alice.logger, None, "Did not populate alice.logger correctly")

    def testString(self):
        should_be_string = ("hello" + "world") if True else ""
        self.assertEqual(type(should_be_string), type("string"), "Adding a string inside a paren isn't a string anymore.")

    def simpleDecorator(self):
        global calls
        calls = 0

        @static_vars(foo=2)
        def testfunc():
            if calls == 0:
                self.assertTrue(testfunc.foo, 2)
                testfunc.foo += 1
            elif calls == 1:
                self.assertTrue(testfunc.foo, 3)
            else:
                self.assertTrue(False)

        testfunc()
        calls += 1
        testfunc()

    def testComplicatedDecorator(self):

        global calls
        calls = 0

        @treeherder_response
        def treeherder(request_type, fullpath):
            if calls == 0:
                self.assertEqual(treeherder.health_calls, 0)
                self.assertEqual(treeherder.jobs_calls, 0)
            elif calls == 1:
                self.assertEqual(treeherder.health_calls, 1)
                self.assertEqual(treeherder.jobs_calls, 0)
            elif calls == 2:
                self.assertEqual(treeherder.health_calls, 1)
                self.assertEqual(treeherder.jobs_calls, 1)

        treeherder(TYPE_HEALTH, "")
        calls += 1
        treeherder(TYPE_JOBS, "")
        calls += 1
        treeherder(TYPE_HEALTH, "")


if __name__ == '__main__':
    unittest.main(verbosity=0)
