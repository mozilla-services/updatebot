#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit, INeedsCommandProvider


class DefaultPhabricatorProvider(INeedsCommandProvider):
    def __init__(self, config):
        super().__init__(config)

    @logEntryExit
    def submit_patch(self):
        self.run(["arc", "diff", "--verbatim"])
