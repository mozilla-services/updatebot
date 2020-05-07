#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit, run_command


class DefaultPhabricatorProvider:
    def __init__(self, config):
        pass

    @logEntryExit
    def submit_patch(self):
        run_command(["arc", "diff", "--verbatim"])
