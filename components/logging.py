# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import Struct
from components.providerbase import BaseProvider

LogLevel = Struct(**{
    'Fatal': 'fatal',
    'Error': 'error',
    'Warning': 'warning',
    'Info': 'info',
    'Debug': 'debug'
})


def logEntryExit(func):
    def func_wrapper(*args, **kwargs):
        obj = args[0]
        assert 'logger' in dir(obj), "If @logEntryExit is applied to a class method, it must inherit INeedsLoggingProvider"
        obj.logger.log("================================================", level=LogLevel.Debug)
        obj.logger.log("Beginning %s" % func.__qualname__, level=LogLevel.Info)
        obj.logger.log(" Arguments: %s" % str(args), level=LogLevel.Info)
        ret = func(*args, **kwargs)
        obj.logger.log("Ending %s" % func.__qualname__, level=LogLevel.Info)
        return ret
    return func_wrapper


class LoggingProvider(BaseProvider):
    def __init__(self, config):
        self.loggers = []
        self._log_category = None
        if 'local' in config and config['local']:
            self.loggers.append(LocalLogger(config))
        if 'sentry' in config and config['sentry']:
            self.loggers.append(SentryLogger(config))

    def _update_config(self, additional_config):
        for l in self.loggers:
            l.update_config(additional_config)

    def bind_category(self, category):
        self._log_category = category
        return self

    def log(self, *args, level=LogLevel.Info, category=None):
        for l in self.loggers:
            l.log(*args, level=level, category=category or self._log_category)

    def log_exception(self, e):
        for l in self.loggers:
            l.log_exception(e)


class LoggerInstance(BaseProvider):
    def __init__(self):
        pass

    def log(self, *args, level, category):
        assert False, "Subclass should implement this function"

    def log_exception(self, e):
        assert False, "Subclass should implement this function"


class LocalLogger(LoggerInstance):
    def __init__(self, config):
        pass

    def log(self, *args, level, category):
        prefix = "[" + level + "] "
        prefix += category + ":" if category else ""
        print(prefix, *args)

    def log_exception(self, e):
        print(str(e))


class SentryLogger(LoggerInstance):
    def __init__(self, config):
        pass

    def log(self, *args, level, category):
        pass

    def log_exception(self, e):
        pass


class SimpleLogger(LoggingProvider):
    def __init__(self):
        super().__init__({'local': True})
