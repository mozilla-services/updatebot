#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class TaskclusterProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self._vcs_setup_initialized = False
        self.url = "https://treeherder.mozilla.org/"
        if 'url' in config:
            self.url = config['url']

        self.project = ""
        if 'project' in config:
            self.project = "project/" + config['project'] + "/"

        self.HEADERS = {
            'User-Agent': 'Updatebot'
        }

    # =================================================================
    # =================================================================
    @logEntryExit
    def _vcs_setup(self):
        if not self._vcs_setup_initialized:
            self.run(["./mach", "vcs-setup", "--update"])
            self._vcs_setup_initialized = True
        self._vcs_setup_initialized = False

    @logEntryExit
    def submit_to_try(self, library):
        self._vcs_setup()
        ret = self.run(
            ["./mach", "try", "auto"])
        output = ret.stdout.decode()

        isNext = False
        try_link = None
        for l in output.split("\n"):
            if isNext:
                try_link = l.replace("remote:", "").strip()
                break
            if "Follow the progress of your build on Treeherder:" in l:
                isNext = True

        if not try_link or "#/jobs?repo=try&revision=" not in try_link:
            raise Exception("Could not find the try link in output:\n" + output)
        try_link = try_link[try_link.index("#/jobs?repo=try&revision=") + len("#/jobs?repo=try&revision="):]
        return try_link
