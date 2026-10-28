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
from components.commandprovider import CommandProvider, TracebackInCommandStderr
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

    def _runner_capturing_exceptions(self):
        runner = self._runner()
        runner.reported = []
        runner.logger = type("CapturingLogger", (), {
            "log": lambda _self, *args, **kwargs: None,
            "log_exception": lambda _self, e: runner.reported.append(e),
        })()
        return runner

    def testTracebackInStderrIsReported(self):
        runner = self._runner_capturing_exceptions()
        ret = runner.run(["python3", "-c", "import traceback\ntry:\n    raise AttributeError('no filteredhash')\nexcept AttributeError:\n    traceback.print_exc()"])
        self.assertEqual(ret.returncode, 0)
        self.assertEqual(len(runner.reported), 1)
        self.assertIsInstance(runner.reported[0], TracebackInCommandStderr)
        self.assertIn("AttributeError: no filteredhash", str(runner.reported[0]))

    def testNoTracebackIsNotReported(self):
        runner = self._runner_capturing_exceptions()
        runner.run(["bash", "-c", "echo just a warning >&2"])
        self.assertEqual(runner.reported, [])

    def testFailedCommandIsNotReported(self):
        # A failing command is handled by its caller, so its traceback isn't reported again.
        runner = self._runner_capturing_exceptions()
        ret = runner.run(["python3", "-c", "raise Exception('boom')"], clean_return=False)
        self.assertEqual(ret.returncode, 1)
        self.assertEqual(runner.reported, [])

    def testNoStdinByDefault(self):
        # Without stdin_path the process gets an empty, non-interactive stdin, so it can't wait on a prompt.
        # Give this process a stdin with data in it, so a child that inherited it would see the data.
        r, w = os.pipe()
        os.write(w, b"inherited")
        os.close(w)
        saved_stdin = os.dup(0)
        os.dup2(r, 0)
        try:
            ret = self._runner().run(["python3", "-c", "import os, sys; print(os.isatty(0), repr(sys.stdin.read()))"], timeout=30)
        finally:
            os.dup2(saved_stdin, 0)
            os.close(saved_stdin)
            os.close(r)
        self.assertEqual(ret.stdout.decode().strip(), "False ''")


if __name__ == '__main__':
    unittest.main(verbosity=0)
