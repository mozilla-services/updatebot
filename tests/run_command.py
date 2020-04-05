#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append("..")
import unittest

from components.utilities import run_command

class TestCommandRunner(unittest.TestCase):
	def testCommand(self):
		ret = run_command(["echo", "Test"])

if __name__ == '__main__':
    unittest.main()
