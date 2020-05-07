#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest
import tests.database
import tests.run_command

loader = unittest.TestLoader()
suite = unittest.TestSuite()

suite.addTests(loader.loadTestsFromModule(tests.database))
suite.addTests(loader.loadTestsFromModule(tests.run_command))

runner = unittest.TextTestRunner(verbosity=3)
result = runner.run(suite)
