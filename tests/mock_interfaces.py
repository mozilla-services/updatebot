#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import inspect
import unittest

sys.path.append(".")
sys.path.append("..")
from components.aiprovider import AIProvider
from components.commandprovider import CommandProvider
from components.libraryprovider import LibraryProvider
from tests.mock_aiprovider import MockAIProvider
from tests.mock_commandprovider import TestCommandProvider
from tests.mock_libraryprovider import MockLibraryProvider

# Each mock and the class it stands in for
MOCKS = [
    (MockAIProvider, AIProvider),
    (TestCommandProvider, CommandProvider),
    (MockLibraryProvider, LibraryProvider),
]


class TestMockInterfaces(unittest.TestCase):
    def testMocksMatchTheClassesTheyMock(self):
        # A mock whose methods drift from the real class lets tests pass against an
        # interface the code no longer has (#104).
        for mock, real in MOCKS:
            for name, method in vars(mock).items():
                if name.startswith("__") or not callable(method):
                    continue
                with self.subTest(mock=mock.__name__, method=name):
                    self.assertTrue(hasattr(real, name), "%s.%s doesn't exist on %s" % (mock.__name__, name, real.__name__))
                    self.assertEqual(inspect.signature(method), inspect.signature(getattr(real, name)),
                                     "%s.%s has a different signature from %s.%s" % (mock.__name__, name, real.__name__, name))


if __name__ == '__main__':
    unittest.main(verbosity=0)
