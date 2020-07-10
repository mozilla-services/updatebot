# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import traceback

from sentry_sdk import init as sentry_init, add_breadcrumb, capture_exception, configure_scope

from components.utilities import Struct
from components.providerbase import BaseProvider
from components.commandrunner import _run

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
        bt = traceback.format_exc()
        print(bt)


class SentryLogger(LoggerInstance):
    def __init__(self, config):
        assert 'sentry' in config and config['sentry']
        assert 'sentry_config' in config, "Sentry logger requires a sentry_config key"
        assert 'url' in config['sentry_config'], "Sentry logger requires a url key in sentry_config"
        self.config = config

    def _update_config(self, additional_config):
        version = "updatebot-"
        version += _run(["git", "rev-parse", "HEAD"], shell=False, clean_return=True).stdout.decode().strip()
        version += "-dirty" if _run(["[[ -z $(git status -s) ]]"], shell=True, clean_return=False).returncode else ""

        environment = ""
        if "TASK_ID" in os.environ:
            environment = "taskcluster"
        else:
            environment = _run(["hostname"], shell=False, clean_return=True).stdout.decode().strip()

        sentry_init(
            dsn=self.config['sentry_config']['url'],
            debug=self.config['sentry_config']['debug'] if 'debug' in self.config['sentry_config'] else False,
            release=version,
            max_breadcrumbs=5000,
            environment=environment)

        with configure_scope() as scope:
            if "TASK_ID" in os.environ:
                scope.set_extra("TASK_ID", os.environ['TASK_ID'])

    def log(self, *args, level, category):
        add_breadcrumb(category=category, level=level, message=" ".join([str(i) for i in args]))

    def log_exception(self, e):
        capture_exception(e)


class SimpleLogger(LoggingProvider):
    def __init__(self):
        super().__init__({'local': True})


simpleLogger = SimpleLogger()

SimpleLoggerConfig = {
    'LoggingProvider': simpleLogger
}


def log(*args):
    simpleLogger.log(*args)
