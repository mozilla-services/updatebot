#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import inspect


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

        A provider may implement its own _update_config to perform actions for
        itself.  Those actions are typically:
          1. Calling update_config on a member provider or a collection of member
             providers it has. Those members should inherit from BaseProvider
             and note that we should only call update_config on them, this allows
             the update_config call to succeed even if they have no INeeds
             super-class or _update_config method.
          2. Using its _update_config as a final init() method where all its
             utility providers are available. (This is why we do the below in
             reverse order.)


        One wrinkle here is that if the derived class (the class of the variable;
        i.e. not any superclasses) inherits from any class with _update_config,
        and doesn't define its own, then one of the _update_config functions on
        the base classes will be called twice. This shouldn't matter.
        """
        classes = self.__class__.mro()
        classes.reverse()
        for c in classes:
            methods = inspect.getmembers(c, predicate=inspect.isfunction)
            for m in methods:
                if m[0] == '_update_config':
                    m[1](self, config)


class INeedsCommandProvider:
    """
    An interface class for Providers that need access to the command runner
    """

    def _update_config(self, config):
        if 'CommandProvider' not in config:
            raise Exception("Config passed to INeedsCommandProvider._update_config is missing 'CommandProvider' key, which must be a class instance implementing a 'run' function")
        self.run = config['CommandProvider'].run


class INeedsLoggingProvider:
    """
    An interface class for Providers that need access to logging
    """

    def _update_config(self, config):
        if 'LoggingProvider' not in config:
            raise Exception("Config passed to INeedsLoggingProvider._update_config is missing 'LoggingProvider' key, which must be a class instance implementing the 'LoggingProvider' interface")
        self.logger = config['LoggingProvider'].bind_category(self.__class__.mro()[0].__name__)
