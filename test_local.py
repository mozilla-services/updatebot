#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Runner for the local, live test tier -- NOT run by test.py / CI.

These tests drive real external backends (e.g. the `claude` CLI) against a real
gecko checkout, so they cost money, are non-deterministic, and are opt-in. Each
test SKIPS if its requirements (api keys, a gecko checkout, CLIs) aren't present.

The tests themselves live in tests/local-tests/. That directory name is not a
valid Python package (the hyphen), so we add it to sys.path and import the test
modules by file name, rather than as tests.local-tests.* .

Usage:
    poetry run ./test_local.py
"""

import os
import sys
import unittest
import importlib

# Repo root (for `components.*`, `apis.*`, localconfig, ...) and the local-tests
# directory (for the test modules and their fixtures) both need to be importable.
sys.path.append(".")
LOCAL_TESTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "local-tests")
sys.path.insert(0, LOCAL_TESTS_DIR)

# Must correspond to the file names in tests/local-tests/
LOCAL_TESTS = [
    "ai_conflict_resolution",
]

modules = [importlib.import_module(t) for t in LOCAL_TESTS]

loader = unittest.TestLoader()
suite = unittest.TestSuite()
for m in modules:
    suite.addTests(loader.loadTestsFromModule(m))

# buffer=False: unlike the deterministic suite, the point of these live tests is
# to watch the real run (provider logs, the AI's reported details) as it happens.
if unittest.TextTestRunner(verbosity=3, buffer=False).run(suite).wasSuccessful():
    exit(0)
else:
    exit(1)
