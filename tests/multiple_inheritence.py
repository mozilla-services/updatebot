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
from tests.mock_commandprovider import TestCommandProvider


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
        self.assertEqual(alice.logger, lp, "Did not populate alice.logger correctly")


if __name__ == '__main__':
    unittest.main()
