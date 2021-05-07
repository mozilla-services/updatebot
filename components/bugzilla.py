#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from apis.bugzilla_api import fileBug, commentOnBug, closeBug, findOpenBugs, markFFVersionAffected
from components.providerbase import BaseProvider, INeedsLoggingProvider
from components.logging import LogLevel, logEntryExit


class CommentTemplates:
    @staticmethod
    def UPDATE_SUMMARY(library, new_release_version, release_timestamp):
        return "Update %s to new version %s from %s" % (
            library.name, new_release_version, release_timestamp)

    @staticmethod
    def UPDATE_DETAILS(num_commits, num_new_commits, commit_details):
        new_commit_str = ""
        if num_new_commits != num_commits:
            if num_new_commits == 1:
                new_commit_str = ", including %s new upstream commit I've never filed a bug on before. (It's the top one.)" % (num_new_commits)
            else:
                new_commit_str = ", including %s new upstream commits I've never filed a bug on before. (They're the top %s.)" % (num_new_commits, num_new_commits)

        return """
This update covers %s commits%s:

%s
""" % (num_commits, new_commit_str, commit_details)

    @staticmethod
    def EXAMINE_COMMITS_SUMMARY(library, new_commits):
        return "Examine %s for %s new commits, culminating in %s (%s)" % (
            library.name, len(new_commits), new_commits[-1].revision, new_commits[-1].commit_date)

    @staticmethod
    def COMMENT_ALSO_AFFECTS(ff_version, repo):
        return "It looks like this set of revision(s) also affects Firefox version %s (which is currently on %s)." % (
            ff_version, repo)

    @staticmethod
    def EXAMINE_COMMITS_BODY(library, task, commit_details, open_dependencies):
        open_dependencies_str = ""
        if open_dependencies:
            open_dependencies = [str(x) for x in open_dependencies]
            open_dependencies_str = """\n
This list only contains new commits, it looks like there are other open dependencies
that contain other commits you should review: Bug """ + ", Bug ".join(open_dependencies)

        return """
We detected new commits to %s %s which is currently at revision %s.%s

Please review these and determine if an update to the library is necessary.
If no update is necessary, this bug may have its security-group cleared and
set to INVALID. If the issue is security-sensitive it should change to a
security group.

%s
        """ % (
            library.name,
            "on branch '" + task.branch + "'" if task.branch else "",
            library.revision,
            open_dependencies_str,
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

In either event, I have done all I can and you will need to take it from here. If you
don't want to land my patch, you can replicate it locally for editing with
`./mach vendor %s`
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
    def COULD_NOT_VENDOR(library, errormessage):
        s = "`./mach vendor %s` failed" % library.yaml_path
        if errormessage:
            s += " with the following message:\n\n"
            for line in errormessage.split("\n"):
                s += "> " + line + "\n"
        return s

    @staticmethod
    def TRY_RUN_SUBMITTED(revision, another=False):
        return "I've submitted a" + ("nother" if another else "") + " try run for this commit: https://treeherder.mozilla.org/#/jobs?repo=try&revision=" + revision

    @staticmethod
    def BUG_SUPERSEDED():
        return """
This bug is being closed because a newer revision of the library is available.
This bug will be marked as a duplicate of it (because although this bug is older, it is superseded by the newer one).
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
    def file_bug(self, library, summary, description, cc_list, needinfo=None, see_also=None, depends_on=None, moco_confidential=False):
        severity = "normal" if self.config['General']['env'] == "dev" else "S3"

        bugID = fileBug(self.config['url'], self.config['apikey'],
                        library.bugzilla_product, library.bugzilla_component,
                        summary, description, severity, cc_list, needinfo, see_also, depends_on, moco_confidential)
        self.logger.log("Filed Bug with ID", bugID, level=LogLevel.Info)
        return bugID

    @logEntryExit
    def comment_on_bug(self, bug_id, comment, needinfo=None, assignee=None):
        commentOnBug(
            self.config['url'], self.config['apikey'], bug_id, comment, needinfo=needinfo, assignee=assignee)
        self.logger.log("Filed Comment on Bug %s" % (bug_id), level=LogLevel.Info)

    @logEntryExit
    def wontfix_bug(self, bug_id, comment):
        closeBug(self.config['url'], self.config['apikey'], bug_id, 'WONTFIX', comment)

    @logEntryExit
    def dupe_bug(self, bug_id, comment, dupe_id):
        closeBug(self.config['url'], self.config['apikey'], bug_id, 'DUPLICATE', comment, dupe_id=dupe_id)

    @logEntryExit
    def find_open_bugs(self, bug_ids):
        if len(bug_ids) > 0:
            return findOpenBugs(self.config['url'], bug_ids)
        return []

    @logEntryExit
    def mark_ff_version_affected(self, bug_id, ff_version, affected=True):
        return markFFVersionAffected(self.config['url'], self.config['apikey'], bug_id, ff_version, affected)
