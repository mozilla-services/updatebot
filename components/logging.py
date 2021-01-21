# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
from enum import unique, IntEnum
import unittest
import traceback
from functools import partial

from sentry_sdk import init as sentry_init, add_breadcrumb, capture_exception, configure_scope

from components.providerbase import BaseProvider
from components.commandrunner import _run


@unique
class LogLevel(IntEnum):
    Fatal = 1
    Error = 2
    Warning = 3
    Info = 4
    Debug = 5
    Debug2 = 6


def logEntryExit(func, print_arg_list=True, header_line=False):
    def func_wrapper(*args, **kwargs):
        obj = args[0]
        assert 'logger' in dir(obj), "If @logEntryExit is applied to a class method, it must inherit INeedsLoggingProvider"
        if header_line:  # When header_line & Debug, we print two on purpose
            obj.logger.log("================================================", level=LogLevel.Info)
        obj.logger.log("================================================", level=LogLevel.Debug)
        obj.logger.log("Beginning %s" % func.__qualname__, level=LogLevel.Info)
        obj.logger.log(" Arguments: %s" % (str(args) if print_arg_list else "[Omitted]"), level=LogLevel.Debug)
        ret = func(*args, **kwargs)
        obj.logger.log("Ending %s" % func.__qualname__, level=LogLevel.Info)
        return ret
    return func_wrapper


logEntryExitNoArgs = partial(logEntryExit, print_arg_list=False, header_line=False)
logEntryExitHeaderLine = partial(logEntryExit, print_arg_list=False, header_line=True)


class LoggingProvider(BaseProvider):
    def __init__(self, config):
        self.loggers = []
        if 'local' in config and config['local']:
            self.loggers.append(LocalLogger(config))
        if 'sentry' in config and config['sentry']:
            self.loggers.append(SentryLogger(config))

    def _update_config(self, additional_config):
        for logger in self.loggers:
            logger.update_config(additional_config)

    def log(self, *args, level=LogLevel.Info, category=None):
        for logger in self.loggers:
            logger.log(*args, level=level, category=category)

    def log_exception(self, e):
        for logger in self.loggers:
            logger.log_exception(e)


class LoggerInstance(BaseProvider):
    def __init__(self):
        pass

    def log(self, *args, level, category):
        assert False, "Subclass should implement this function"

    def log_exception(self, e):
        assert False, "Subclass should implement this function"


class LocalLogger(LoggerInstance):
    def __init__(self, config):
        if 'UPDATEBOT_LOG_LEVEL' in os.environ:
            self.min_log_level = LogLevel(int(os.environ['UPDATEBOT_LOG_LEVEL']))
        else:
            self.min_log_level = LogLevel.Info

        self.log_component = os.environ.get('UPDATEBOT_LOG_COMPONENT', "").lower()

    def log(self, *args, level, category):
        if category and self.log_component not in category.lower():
            return
        if level.value <= self.min_log_level:
            prefix = ("[" + level.name + "]").ljust(9)
            prefix += (" " + category + ":") if category else ""
            print(prefix, *args, flush=True)

    def log_exception(self, e):
        bt = traceback.format_exc()
        print(bt, flush=True)


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


class SimpleLoggingTest(unittest.TestCase, SimpleLogger):
    def __init__(self, *kwargs):
        SimpleLogger.__init__(self)
        unittest.TestCase.__init__(self, *kwargs)
        self.logger = self


simpleLogger = SimpleLogger()

SimpleLoggerConfig = {
    'LoggingProvider': simpleLogger
}


def log(*args, **kwargs):
    simpleLogger.log(*args, **kwargs)
