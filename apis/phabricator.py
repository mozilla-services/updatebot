#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class PhabricatorProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def submit_patch(self):
        ret = self.run(["arc", "diff", "--verbatim"])
        output = ret.stdout.decode()

        isNext = False
        phab_revision = "Unknown"
        for l in output.split("\n"):
            if isNext:
                phab_revision = l.split(" ")[0].replace("(D", "").replace(")", "")
                break
            if "Completed" == l.strip():
                isNext = True

        return phab_revision
