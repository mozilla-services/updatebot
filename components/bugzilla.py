#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from apis.bugzilla_api import fileBug, commentOnBug
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel, logEntryExit


class CommentTemplates:
    @staticmethod
    def DONE_BUILD_FAILURE(library):
        return """
It looks like we experienced one or more build failures when trying to apply this
update. You will need to apply this update manually; you can replicate the patch
locally with `./mach vendor %s`.  I'm going to abandon the Phabricator patch and
let you submit a new one.

If the build failure wasn't caused by a library change, and was instead caused by
something structural in the build system (like I didn't automatically correct the
moz.build file correctly) - please let my maintainers know in Slack:#secinf so I
can be improved.
""" % (library.yaml_path)

    @staticmethod
    def DONE_CLASSIFIED_FAILURE(prefix, library):
        return prefix + "\n" + """
These failures may mean that the library update succeeded; you'll need to review
them yourself and decide. If there are lint failures, you will need to fix them in
a follow-up patch. (Or ignore the patch I made, and recreate it yourself with
`./mach vendor %s`.)

In either event, I have done all I can, so you will need to take it from here.
""" % (library.yaml_path)

    @staticmethod
    def DONE_UNCLASSIFIED_FAILURE(prefix, library):
        return prefix + "\n" + """
These failures probably mean that the library update changed something and caused
tests to fail. You'll need to review them yourself and decide where to go from here.

In either event, I have done all I can, so I'm abandoning this revision and you will
need to take it from here. You can replicate the patch locally with `./mach vendor %s`
""" % (library.yaml_path)

    @staticmethod
    def DONE_ALL_SUCCESS():
        return """
All the jobs in the try run succeeded. Like literally all of them, there weren't
even any intermittents. That is pretty surprising to me, so maybe you should double
check to make sure I didn't misinterpret things and that the correct tests ran...

Anyway, I've done all I can, so I'm passing to you to review and land the patch.
"""

    @staticmethod
    def VENDOR_FAILED(message):
        s = "`./mach vendor %s` failed"
        if message:
            s += " with the following message:\n\n"
            for m in message.split("\n"):
                s += "> " + m
        return s

    @staticmethod
    def TRY_RUN_SUBMITTED(revision):
        return "I've submitted a try run for this commit: https://treeherder.mozilla.org/#/jobs?repo=try&revision=" + revision


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
    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        commentOnBug(
            self.config['url'], self.config['apikey'], bug_id, comment, needinfo=needinfo, assignee=assignee)
        self.logger.log("Filed Comment on Bug %s" % (bug_id), level=LogLevel.Info)
