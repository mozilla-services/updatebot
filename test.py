#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest
import tests.database
import tests.bugzilla
import tests.automation_configuration
import tests.run_command
import tests.functionality

loader = unittest.TestLoader()
suite = unittest.TestSuite()

suite.addTests(loader.loadTestsFromModule(tests.database))
suite.addTests(loader.loadTestsFromModule(tests.bugzilla))
suite.addTests(loader.loadTestsFromModule(tests.automation_configuration))
suite.addTests(loader.loadTestsFromModule(tests.run_command))
suite.addTests(loader.loadTestsFromModule(tests.functionality))

runner = unittest.TextTestRunner(verbosity=3)
result = runner.run(suite)

raise ValueError('A very specific bad thing happened.')
