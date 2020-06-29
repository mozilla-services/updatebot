# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import BaseProvider


class LoggingProvider(BaseProvider):
    def __init__(self, config):
        self.loggers = []
        if 'loggers' in config:
            self.loggers = config['loggers']
        self._log_category = None

    def bind_category(self, category):
        self._log_category = category
        return self

    def log(self, *args, category=None):
        for l in self.loggers:
            l.log(*args, category=category or self._log_category)

    def log_exception(self, e):
        for l in self.loggers:
            l.log_exception(e)


class LoggerInstance:
    def __init__(self):
        pass

    def log(self, *args, category):
        assert False, "Subclass should implement this function"

    def log_exception(self, e):
        assert False, "Subclass should implement this function"


class LocalLogger(LoggerInstance):
    def __init__(self):
        pass

    def log(self, *args, category):
        prefix = category + ":" if category else ""
        print(prefix, *args)

    def log_exception(self, e):
        print(str(e))


class SentryLogger(LoggerInstance):
    def __init__(self):
        pass

    def log(self, *args, category):
        pass

    def log_exception(self, e):
        pass
