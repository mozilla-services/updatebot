#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import time
import subprocess
from subprocess import PIPE

from components.utilities import BaseProvider, INeedsLoggingProvider


class DefaultCommandProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def run(self, args, shell=False, clean_return=True):
        ran_successfully = False
        stdout = None
        stderr = None
        exception = None

        self.logger.log("----------------------------------------------")
        start = time.time()
        self.logger.log("Running", args)
        try:
            ret = subprocess.run(
                args, shell=shell, stdout=PIPE, stderr=PIPE, timeout=60 * 10)
        except subprocess.TimeoutExpired as e:
            ran_successfully = False
            stdout = e.stdout
            stderr = e.stderr
            exception = e
        else:
            ran_successfully = True
            stdout = ret.stdout.decode()
            stderr = ret.stderr.decode()

        if not ran_successfully:
            self.logger.log("Command Timed Out. Will abort....")
        else:
            self.logger.log("Return:", ret.returncode,
                            "Runtime (s):", int(time.time() - start))
        self.logger.log("-------")
        self.logger.log("stdout:")
        self.logger.log(stdout)
        self.logger.log("-------")
        self.logger.log("stderr:")
        self.logger.log(stderr)
        self.logger.log("----------------------------------------------")
        if not ran_successfully:
            raise exception
        if ran_successfully and clean_return:
            if ret.returncode:
                self.logger.log("Expected a clean process return but got:", ret.returncode)
                self.logger.log("   (", *args, ")")
                self.logger.log("Exiting application...")
                ret.check_returncode()
        return ret
