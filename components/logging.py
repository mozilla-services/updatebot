# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import BaseProvider


class DefaultLoggingProvider(BaseProvider):
    def __init__(self, config):
        self.loggers = []
        if 'loggers' in config:
            self.loggers = config['loggers']

    def log(self, *args):
        for l in self.loggers:
            l.log(*args)

    def log_exception(self, e):
        for l in self.loggers:
            l.log_exception(e)


class LoggerInstance:
    def __init__(self):
        pass

    def log(self, *args):
        assert False, "Subclass should implement this function"

    def log_exception(self, e):
        assert False, "Subclass should implement this function"


class LocalLogger(LoggerInstance):
    def __init__(self):
        pass

    def log(self, *args):
        print(*args)

    def log_exception(self, e):
        print(str(e))


class SentryLogger(LoggerInstance):
    def __init__(self):
        pass

    def log(self, *args):
        pass

    def log_exception(self, e):
        pass
