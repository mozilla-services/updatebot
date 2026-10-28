#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from functools import partial

from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.commandrunner import _run
from components.logging import LogLevel


class TracebackInCommandStderr(Exception):
    """A command succeeded but printed a Python traceback to stderr, e.g. a
    mercurial extension that failed to load."""
    pass


class CommandProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def _update_config(self, additional_config):
        self.errorlog = partial(self.logger.log, level=LogLevel.Error)
        self.infolog = partial(self.logger.log, level=LogLevel.Info)
        self.debuglog = partial(self.logger.log, level=LogLevel.Debug)

    def run(self, args, shell=False, clean_return=True, cwd=None, stdin_path=None, timeout=60 * 20, env=None):
        ret = _run(args, shell=shell, clean_return=clean_return,
                   errorlog=self.errorlog, infolog=self.infolog, debuglog=self.debuglog,
                   cwd=cwd, stdin_path=stdin_path, timeout=timeout, env=env)
        if ret.returncode == 0:
            self._report_traceback_in_stderr(args, ret.stderr)
        return ret

    def _report_traceback_in_stderr(self, args, stderr):
        stderr = stderr.decode(errors="replace") if stderr else ""
        if "Traceback (most recent call last):" not in stderr:
            return
        lines = [line for line in stderr.strip().splitlines() if line.strip()]
        message = "Command %s succeeded but printed a traceback to stderr: %s" % (args, lines[-1].strip())
        self.logger.log(message, level=LogLevel.Warning)
        try:
            raise TracebackInCommandStderr(message)
        except TracebackInCommandStderr as e:
            self.logger.log_exception(e)
