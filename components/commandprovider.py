#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from functools import partial

from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.commandrunner import _run
from components.logging import LogLevel


class CommandProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    def _update_config(self, additional_config):
        self.errorlog = partial(self.logger.log, level=LogLevel.Error)
        self.infolog = partial(self.logger.log, level=LogLevel.Info)
        self.debuglog = partial(self.logger.log, level=LogLevel.Debug)

    def run(self, args, shell=False, clean_return=True):
        return _run(args, shell=shell, clean_return=clean_return,
                    errorlog=self.errorlog, infolog=self.infolog, debuglog=self.debuglog)
