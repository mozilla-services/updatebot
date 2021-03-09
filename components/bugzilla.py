#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from apis.bugzilla_api import fileBug, commentOnBug, closeBug
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel, logEntryExit


class CommentTemplates:
    @staticmethod
    def UPDATE_SUMMARY(library, new_release_version, release_timestamp):
        return "Update %s to new version %s from %s" % (
            library.name, new_release_version, release_timestamp)

    @staticmethod
    def EXAMINE_COMMITS_SUMMARY(library, new_commits):
        return "Examine %s for %s new commits, culminating in %s (%s)" % (
            library.name, len(new_commits), new_commits[-1].revision, new_commits[-1].commit_date)

    @staticmethod
    def EXAMINE_COMMITS_BODY(library, task, commit_details):
        return """
We detected new commits to %s %s which is currently at revision %s.

Please review these and determine if an update to the library is necessary.
If no update is necessary, this bug may have its security-group cleared and
set to INVALID. If the issue is security-sensitive it should change to a
security group.

%s
        """ % (
            library.name,
            "on branch '" + task.branch + "'" if task.branch else "",
            library.revision,
            commit_details
        )

    @staticmethod
    def DONE_BUILD_FAILURE(library):
        return """
It looks like we experienced one or more build failures when trying to apply this
update. You will need to apply this update manually; you can replicate the patch
locally with `./mach vendor %s`.  I'm going to abandon the Phabricator patch and
let you submit a new one.

If the build failure wasn't caused by a library change, and was instead caused by
something structural in the build system please let my maintainers know in
Slack:#secinf.

I do my best to automatically add new files to the build, but some moz.build files
are complicated and you may need to fix them manually.
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
These failures could mean that the library update changed something and caused
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
    def COULD_NOT_VENDOR(message):
        s = "`./mach vendor %s` failed"
        if message:
            s += " with the following message:\n\n"
            for m in message.split("\n"):
                s += "> " + m
        return s

    @staticmethod
    def TRY_RUN_SUBMITTED(revision, another=False):
        return "I've submitted a" + ("nother" if another else "") + " try run for this commit: https://treeherder.mozilla.org/#/jobs?repo=try&revision=" + revision

    @staticmethod
    def BUG_SUPERSEDED():
        return """
This bug is being closed because a newer revision of the library is available.
It will be linked in the See Also field.
"""


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
    def file_bug(self, library, summary, description, cc_list, see_also=None, depends_on=None, moco_confidential=False):
        severity = "normal" if self.config['General']['env'] == "dev" else "S3"

        bugID = fileBug(self.config['url'], self.config['apikey'],
                        library.bugzilla_product, library.bugzilla_component,
                        summary, description, severity, cc_list, see_also, depends_on, moco_confidential)
        self.logger.log("Filed Bug with ID", bugID, level=LogLevel.Info)
        return bugID

    @logEntryExit
    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        commentOnBug(
            self.config['url'], self.config['apikey'], bug_id, comment, needinfo=needinfo, assignee=assignee)
        self.logger.log("Filed Comment on Bug %s" % (bug_id), level=LogLevel.Info)

    @logEntryExit
    def close_bug(self, bug_id, comment):
        closeBug(self.config['url'], self.config['apikey'], bug_id, comment)
