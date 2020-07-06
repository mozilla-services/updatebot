#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest
import importlib

# Must correspond to the file name
TESTS = [
    "database",
    "bugzilla",
    "automation_configuration",
    "run_command",
    "functionality",
    "multiple_inheritence",
]

modules = []
for t in TESTS:
    modules.append(importlib.import_module("tests." + t))

loader = unittest.TestLoader()
suite = unittest.TestSuite()

for m in modules:
    suite.addTests(loader.loadTestsFromModule(m))

if unittest.TextTestRunner(verbosity=3).run(suite).wasSuccessful():
    exit(0)
else:
    exit(1)
