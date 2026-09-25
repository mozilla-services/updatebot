#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import tempfile
import unittest

sys.path.append(".")
sys.path.append("..")
from components.commandprovider import CommandProvider
from components.logging import SimpleLoggerConfig


class TestCommandRunner(unittest.TestCase):
    def _runner(self):
        runner = CommandProvider({})
        runner.update_config(SimpleLoggerConfig)
        return runner

    def testCommand(self):
        ret = self._runner().run(["echo", "Test"])
        self.assertEqual(ret.returncode, 0, "Did not run the command successfully")

    def testEnvIsMergedOverEnviron(self):
        # A provided env var reaches the child, layered on top of the inherited environment.
        ret = self._runner().run(["bash", "-c", "echo $UPDATEBOT_TEST_VAR"],
                                 env={"UPDATEBOT_TEST_VAR": "hello"})
        self.assertEqual(ret.returncode, 0)
        self.assertEqual(ret.stdout.decode().strip(), "hello")

    def testCwd(self):
        with tempfile.TemporaryDirectory() as d:
            ret = self._runner().run(["pwd"], cwd=d)
            self.assertEqual(ret.returncode, 0)
            self.assertEqual(os.path.realpath(ret.stdout.decode().strip()), os.path.realpath(d))

    def testStdinPath(self):
        # The contents of stdin_path are fed to the process's standard input.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("piped-in-content")
            stdin_path = f.name
        try:
            ret = self._runner().run(["cat"], stdin_path=stdin_path)
            self.assertEqual(ret.returncode, 0)
            self.assertEqual(ret.stdout.decode(), "piped-in-content")
        finally:
            os.remove(stdin_path)


if __name__ == '__main__':
    unittest.main(verbosity=0)
