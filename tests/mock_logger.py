# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append("..")
from components.logging import SimpleLogger

simpleLogger = SimpleLogger()

TestLoggerConfig = {
    'LoggingProvider': simpleLogger
}


def log(*args):
    simpleLogger.log(*args)
