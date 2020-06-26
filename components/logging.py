# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import BaseProvider


class DefaultLoggingProvider(BaseProvider):
    def __init__(self, config):
        self.loggers = []
        pass


class LoggerInstance:
    def __init__(self):
        pass


class LocalLoger(LoggerInstance):
    def __init__(self):
        pass


class SentryLogger(LoggerInstance):
    def __init__(self):
        pass
