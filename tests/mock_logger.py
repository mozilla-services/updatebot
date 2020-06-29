# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append("..")
from components.logging import LoggingProvider, LocalLogger

TestLoggerConfig = {
    'LoggingProvider': LoggingProvider({
        'loggers': [LocalLogger()]
    })
}


def log(*args):
    TestLoggerConfig['LoggingProvider']['loggers'][0].log(*args)
