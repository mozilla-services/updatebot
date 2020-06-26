# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import BaseProvider


class DefaultLoggingProvider(BaseProvider):
    def __init__(self, config):
        self.loggers = []
        if 'loggers' in config:
            self.loggers = config['loggers']
        pass

    def log(self, message):
        for l in self.loggers:
            l.log(message)


class LoggerInstance:
    def __init__(self):
        pass

    def log(self, message):
        assert False, "log should be overwritten in a child class"


class LocalLogger(LoggerInstance):
    def __init__(self):
        pass

    def log(self, message):
        print(message)


class SentryLogger(LoggerInstance):
    def __init__(self):
        pass

    def log(self, message):
        pass
