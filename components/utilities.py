#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import time
import inspect
import subprocess
from subprocess import PIPE


def logEntryExit(func):
    def func_wrapper(*args, **kwargs):
        print("================================================")
        print("Beginning", func.__qualname__)
        print(" Arguments:", *args)
        ret = func(*args, **kwargs)
        print("Ending", func.__qualname__)
        return ret
    return func_wrapper


class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)


class BaseProvider:
    """
    All Providers - even test providers - must inherit from BaseProvider.
    We expect an update_config method to be present on all providers, as it
    will be called.

    _update_config will most commonly be defined on INeeds interfaces, but can
    be present on a derived class also.
    """

    def update_config(self, config):
        """
        update_config iterates through all the classes in the inheritence chain
        and looks for an _update_config method on that class. If it is present,
        it is called.

        One wrinkle here is that if the derived class (the class of the variable;
        i.e. not any superclasses) inherits from any class with _update_config,
        and doesn't define its own, then one of the _update_config functions on
        the base classes will be called twice. This shouldn't matter.
        """
        for c in self.__class__.mro():
            methods = inspect.getmembers(c, predicate=inspect.isfunction)
            for m in methods:
                if m[0] == '_update_config':
                    m[1](self, config)


class INeedsCommandProvider:
    """
    An interface class for Providers that need access to the command runner
    """

    def _update_config(self, config):
        self.run = config['CommandProvider'].run


class INeedsLoggingProvider:
    """
    An interface class for Providers that need access to logging
    """

    def _update_config(self, config):
        self.logger = config['LoggingProvider']


class DefaultCommandProvider(BaseProvider):
    def __init__(self, config):
        pass

    def run(self, args, shell=False, clean_return=True):
        ran_successfully = False
        stdout = None
        stderr = None
        exception = None

        print("----------------------------------------------")
        start = time.time()
        print("Running", args)
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
            print("Command Timed Out. Will abort....")
        else:
            print("Return:", ret.returncode,
                  "Runtime (s):", int(time.time() - start))
        print("-------")
        print("stdout:")
        print(stdout)
        print("-------")
        print("stderr:")
        print(stderr)
        print("----------------------------------------------")
        if not ran_successfully:
            raise exception
        if ran_successfully and clean_return:
            if ret.returncode:
                print("Expected a clean process return but got:", ret.returncode)
                print("   (", *args, ")")
                print("Exiting application...")
                ret.check_returncode()
        return ret
