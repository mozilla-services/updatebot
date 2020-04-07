#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from apis.bugzilla_api import fileBug, commentOnBug
from components.dbmodels import JOBSTATUS
from components.utilities import logEntryExit

class DefaultBugzillaProvider:
    def __init__(self, config):
        pass

    @logEntryExit
    def file_bug(self, library, new_release_version):
        summary = "Update %s to new version %s" % (
            library.shortname, new_release_version)
        description = ""

        bugID = fileBug(library.bugzilla_product,
                        library.bugzilla_component, summary, description)
        print("Filed Bug with ID", bugID)
        return bugID

    @logEntryExit
    def comment_on_bug(self, bug_id, status, try_run=None):
        if status == JOBSTATUS.COULD_NOT_VENDOR:
            comment = "./mach vendor failed with the following message: <TODO>"
        else:
            comment = "I've submitted a try run for this commit: " + try_run
        commentID = commentOnBug(bug_id, comment)
        print("Filed Comment with ID %s on Bug %s" % (commentID, bug_id))

