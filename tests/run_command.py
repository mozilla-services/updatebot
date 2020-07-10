#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import unittest

sys.path.append(".")
sys.path.append("..")
from components.commandprovider import CommandProvider
from components.logging import SimpleLoggerConfig


class TestCommandRunner(unittest.TestCase):
    def testCommand(self):
        runner = CommandProvider({})
        runner.update_config(SimpleLoggerConfig)
        ret = runner.run(["echo", "Test"])
        self.assertEqual(ret.returncode, 0, "Did not run the command successfully")


if __name__ == '__main__':
    unittest.main()
