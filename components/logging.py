# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import gzip
import json
from enum import unique, IntEnum
import unittest
import traceback
from functools import partial, wraps

import sentry_sdk
from sentry_sdk import init as sentry_init, add_breadcrumb, capture_exception
from sentry_sdk.transport import HttpTransport

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
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        obj = args[0]
        assert 'logger' in dir(obj), "If @logEntryExit is applied to a class method, it must inherit INeedsLoggingProvider"
        if header_line:  # When header_line & Debug, we print two on purpose
            obj.logger.log("================================================", level=LogLevel.Info)
        obj.logger.log("================================================", level=LogLevel.Debug)
        obj.logger.log("Beginning %s" % func.__qualname__, level=LogLevel.Info)
        obj.logger.log(" Arguments: %s" % (str(args) + " " + str(kwargs) if print_arg_list else "[Omitted %s args]" % str(len(args) + len(kwargs))), level=LogLevel.Debug)
        ret = func(*args, **kwargs)
        if ret is list:
            obj.logger.log("Function returned a list of %s objects" % len(ret), level=LogLevel.Debug)
        else:
            return_string = str(ret)
            if len(return_string) > 100:
                return_string = return_string[0:100] + "..."
            obj.logger.log("Function returned %s" % return_string, level=LogLevel.Debug)
        obj.logger.log("Ending %s" % func.__qualname__, level=LogLevel.Info)
        return ret
    return func_wrapper


logEntryExitNoArgs = partial(logEntryExit, print_arg_list=False, header_line=False)
logEntryExitHeaderLine = partial(logEntryExit, print_arg_list=False, header_line=True)


class LoggingProvider(BaseProvider):
    context = ""

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
        if LoggingProvider.context != "":
            category = f"{category} {LoggingProvider.context}"
        for logger in self.loggers:
            logger.log(*args, level=level, category=category)

    def log_exception(self, e):
        for logger in self.loggers:
            logger.log_exception(e)

    @staticmethod
    def set_context(library_name, job_id=None):
        LoggingProvider.context = library_name
        if job_id:
            LoggingProvider.context += " job_id=" + str(job_id)

    @staticmethod
    def clear_context():
        LoggingProvider.context = ""


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
        elif 'level' in config:
            self.min_log_level = LogLevel(config['level'])
        elif "TASK_ID" in os.environ:
            self.min_log_level = LogLevel.Debug
        else:
            self.min_log_level = LogLevel.Info

        self.log_component = os.environ.get('UPDATEBOT_LOG_COMPONENT', "").lower()

    def log(self, *args, level, category):
        if category and self.log_component not in category.lower():
            return
        if level.value <= self.min_log_level:
            prefix = ("[" + level.name + "]").ljust(9)
            prefix += ("(" + category + ")") if category else ""
            print(prefix, *args, flush=True)

    def log_exception(self, e):
        bt = traceback.format_exc()
        print(bt, flush=True)


# Sentry rejects events over 1 MB uncompressed or 200 KB compressed
# (https://docs.sentry.io/concepts/data-management/size-limits/). It measures events after
# processing them, which makes ours about 1.5x larger than what we send, so aim well below.
SENTRY_MAX_EVENT_BYTES = 500_000
SENTRY_MAX_COMPRESSED_EVENT_BYTES = 150_000
# Longer breadcrumbs (usually command output) keep only their beginning and end.
SENTRY_MAX_BREADCRUMB_LENGTH = 8192
# A backstop for any other string in an event, such as an exception message.
SENTRY_MAX_VALUE_LENGTH = 65536


def _print_sentry_problem(level, message):
    print(("[" + level.name + "]").ljust(9) + "(SentryLogger)", message, flush=True)


def _shorten_breadcrumb(message):
    if len(message) <= SENTRY_MAX_BREADCRUMB_LENGTH:
        return message
    half = SENTRY_MAX_BREADCRUMB_LENGTH // 2
    return "%s\n[... %d characters omitted ...]\n%s" % (message[:half], len(message) - 2 * half, message[-half:])


def _sentry_event_sizes(event):
    data = json.dumps(event, default=str, separators=(",", ":")).encode()
    return len(data), len(gzip.compress(data))


def _event_fits(event):
    size, compressed_size = _sentry_event_sizes(event)
    return size <= SENTRY_MAX_EVENT_BYTES and compressed_size <= SENTRY_MAX_COMPRESSED_EVENT_BYTES


def trim_sentry_event(event, hint):
    """
    A before_send hook that drops the oldest breadcrumbs until the event is small enough
    for Sentry to accept, keeping as many of the most recent ones as fit.
    """
    # The SDK discards the event if this hook raises, so never let it raise
    try:
        _trim_sentry_event(event)
    except Exception as e:
        _print_sentry_problem(LogLevel.Error, "Could not check the size of Sentry event %s: %r" % (event.get("event_id"), e))
    return event


def _trim_sentry_event(event):
    if _event_fits(event):
        return
    breadcrumbs = event.get("breadcrumbs", {}).get("values", [])

    if breadcrumbs:
        # Reserve room for this before measuring
        event.setdefault("extra", {})["breadcrumbs_dropped_to_fit_size_limit"] = len(breadcrumbs)

        # Binary search for the largest number of most-recent breadcrumbs that fits
        lo, hi = 0, len(breadcrumbs)
        while lo < hi:
            keep = (lo + hi + 1) // 2
            event["breadcrumbs"]["values"] = breadcrumbs[-keep:]
            if _event_fits(event):
                lo = keep
            else:
                hi = keep - 1
        event["breadcrumbs"]["values"] = breadcrumbs[-lo:] if lo else []

        dropped = len(breadcrumbs) - lo
        event["extra"]["breadcrumbs_dropped_to_fit_size_limit"] = dropped
        size, compressed_size = _sentry_event_sizes(event)
        _print_sentry_problem(LogLevel.Warning, "Dropped the oldest %d of %d breadcrumbs from Sentry event %s so it fits Sentry's size limit; it is now %d bytes (%d compressed)." % (
            dropped, len(breadcrumbs), event.get("event_id"), size, compressed_size))

    if not _event_fits(event):
        _print_sentry_problem(LogLevel.Error, "Sentry event %s is too large even without breadcrumbs; Sentry will probably reject it." % event.get("event_id"))


class LoggingSentryTransport(HttpTransport):
    """
    The SDK only logs events that Sentry didn't accept when debug is on, so report them
    in our own log.
    """
    def on_dropped_event(self, reason):
        if reason == "status_413":
            _print_sentry_problem(LogLevel.Error, "Sentry rejected an event because it was too large (HTTP 413).")
        else:
            _print_sentry_problem(LogLevel.Error, "An event was not sent to Sentry, or Sentry did not accept it: %s" % reason)


class SentryLogger(LoggerInstance):
    def __init__(self, config):
        assert 'sentry' in config and config['sentry']
        assert 'sentry_config' in config, "Sentry logger requires a sentry_config key"
        assert 'url' in config['sentry_config'], "Sentry logger requires a url key in sentry_config"
        self.config = config

    def _update_config(self, additional_config):
        version = "updatebot-"
        version += _run(["git", "rev-parse", "HEAD"], shell=False, clean_return=True).stdout.decode().strip()

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
            max_value_length=SENTRY_MAX_VALUE_LENGTH,
            before_send=trim_sentry_event,
            transport=LoggingSentryTransport,
            environment=environment)

        if "TASK_ID" in os.environ:
            sentry_sdk.set_extra("TASK_ID", os.environ['TASK_ID'])

    def log(self, *args, level, category):
        add_breadcrumb(category=category, level=level, message=_shorten_breadcrumb(" ".join([str(i) for i in args])))

    def log_exception(self, e):
        capture_exception(e)


class SimpleLogger(LoggingProvider):
    def __init__(self, config=None):
        super().__init__(config or {'local': True})


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
