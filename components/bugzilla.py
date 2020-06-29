#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from apis.bugzilla_api import fileBug, commentOnBug
from components.dbmodels import JOBSTATUS
from components.utilities import logEntryExit, BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel


class BugzillaProvider(BaseProvider, INeedsLoggingProvider):
    def __init__(self, config):
        self.config = config
        assert 'apikey' in self.config, "apikey must be provided in the Bugzilla Configration"
        if 'url' not in self.config:
            if self.config['General']['env'] == "dev":
                self.config['url'] = "https://bugzilla-dev.allizom.org/rest/"
            elif self.config['General']['env'] == "prod":
                self.config['url'] = "https://bugzilla.mozilla.org/rest/"
            else:
                assert ('url' in self.config) or (self.config['General']['env'] in ["dev", "prod"]), "No bugzilla url provided, and unknown operating environment"

    @logEntryExit
    def file_bug(self, library, new_release_version):
        summary = "Update %s to new version %s" % (
            library.shortname, new_release_version)
        description = ""
        severity = "normal" if self.config['General']['env'] == "dev" else "S3"

        bugID = fileBug(self.config['url'], self.config['apikey'],
                        library.bugzilla_product, library.bugzilla_component,
                        summary, description, severity)
        self.logger.log("Filed Bug with ID", bugID, level=LogLevel.Info)
        return bugID

    @logEntryExit
    def comment_on_bug(self, bug_id, status, try_run=None):
        if status == JOBSTATUS.COULD_NOT_VENDOR:
            comment = "./mach vendor failed with the following message: <TODO>"
        else:
            comment = "I've submitted a try run for this commit: https://treeherder.mozilla.org/#/jobs?repo=try&revision=" + try_run
        commentID = commentOnBug(
            self.config['url'], self.config['apikey'], bug_id, comment)
        self.logger.log("Filed Comment with ID %s on Bug %s" % (commentID, bug_id), level=LogLevel.Info)
