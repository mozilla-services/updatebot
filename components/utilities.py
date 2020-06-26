#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import inspect


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
