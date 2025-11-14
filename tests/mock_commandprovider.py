#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append(".")
sys.path.append("..")

import inspect
import subprocess

from components.utilities import Struct
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel


# sentinal value to indicate we should really execute the command.
DO_EXECUTE = "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f"


class TestCommandProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self.mappings = {}
        if 'test_mappings' in config:
            self.mappings = config['test_mappings']

        self.real_runner = None
        if 'real_runner' in config:
            self.real_runner = config['real_runner']

    def run(self, args, shell=False, clean_return=True):
        argument_string = args
        if isinstance(args, list):
            argument_string = " ".join(args)
        self.logger.log("Mocked Command executed", argument_string, level=LogLevel.Info)

        stdout = None
        returncode = 0
        for m in self.mappings:
            if argument_string.startswith(m):
                if self.mappings[m] == DO_EXECUTE:
                    if not self.real_runner:
                        raise Exception("TestCommandProvider was asked to really execute something; but doesn't have a means to do so")
                    return self.real_runner.run(args, shell=shell, clean_return=clean_return)
                else:
                    func = self.mappings[m]

                    # If the lambda for this output expects a parameter, give it the command we want to execute
                    # But we don't require a parameter
                    if len(inspect.signature(func).parameters) > 0:
                        retval = func(argument_string)
                    else:
                        retval = func()

                    self.logger.log("We found a mapped response, providing it.", level=LogLevel.Info)

                    if isinstance(retval, tuple):
                        returncode = retval[0]
                        stdout = retval[1]
                    else:
                        stdout = retval

                    if returncode:
                        self.logger.log("... and it has a failing return code.", level=LogLevel.Info)
                        if clean_return:
                            raise subprocess.CalledProcessError(returncode, args)

                    self.logger.log("---\n%s\n---" % stdout, level=LogLevel.Debug2)
                break

        if stdout is None:
            self.logger.log("We did not find a mapped response for the command `%s`." % argument_string, level=LogLevel.Warning)

        def check_returncode():
            if returncode != 0:
                raise subprocess.CalledProcessError(returncode, argument_string)
            pass
        return Struct(**{'stdout':
                         Struct(**{'decode': lambda: stdout}),
                         'returncode': returncode,
                         'check_returncode': check_returncode})
