# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class MercurialProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def reset_repository(self):
        # Throws away everything Updatebot did to the checkout: uncommitted changes,
        # and its commits.
        self.run(["hg", "checkout", "-C", "."])
        self.run(["hg", "purge", "."])

        original_revision = os.environ.get("GECKO_HEAD_REV", "")
        if original_revision:
            self.run(["hg", "update", original_revision])
        else:
            ret = self.run(["hg", "strip", "roots(outgoing())", "--no-backup"], clean_return=False)
            if ret.returncode == 255:
                if "abort: empty revision set" not in ret.stderr:
                    ret.check_returncode()

    @logEntryExit
    def current_revision(self):
        # -l 1: some hg configurations make `hg log` follow history, listing more than one
        return self.run(["hg", "log", "-r", ".", "-l", "1", "-T", "{node}"]).stdout.strip()

    @logEntryExit
    def commit_stage(self, library, index, message):
        """Commit what a vendoring stage changed. Returns False, committing nothing, if
        it changed nothing."""
        if index > 0:
            # The old format's `./mach vendor --patch-mode only` doesn't register files
            # the patches add or delete (only a full vendor does), so do that here or
            # they'd be left out.
            self.run(["hg", "addremove", "-q", library.vendor_directory, os.path.dirname(library.yaml_path)])
        if not self.run(["hg", "status", "--modified", "--added", "--removed"]).stdout.strip():
            return False
        self.run(["hg", "commit", "-m", message])
        return True

    @logEntryExit
    def changes_since(self, revision, exclude=()):
        # Files whose contents differ between revision and the working directory, with
        # paths relative to the root of the checkout. Not `hg status --rev`, which
        # counts a file changed and then changed back as modified.
        excluded = set(os.path.normpath(p) for p in exclude)
        diff = self.run(["hg", "diff", "--git", "-r", revision]).stdout
        files = set()
        for line in diff.splitlines():
            m = re.match(r"^diff --git a/(.*) b/(.*)$", line)
            if m:
                files.update(m.groups())
        return sorted(f for f in files if os.path.normpath(f) not in excluded)

    def commits_since(self, revision):
        # Not every descendant: other libraries' commits stay behind as other children
        # of the same revision when GECKO_HEAD_REV is set, as reset_repository() then
        # updates rather than strips.
        return self.run(["hg", "log", "-r", "%s::. - %s" % (revision, revision), "-T", "{node}\n"]).stdout.split()

    @logEntryExit
    def reword_commits_since(self, revision, messages):
        """Give the commits between revision and the working directory's parent these
        messages, oldest first. Done by copying them with graft and amending each copy,
        which needs no extensions, unlike evolve's metaedit on a commit with children."""
        commits = self.commits_since(revision)
        assert len(commits) == len(messages), "Expected %s commits to reword, found %s" % (len(messages), len(commits))
        if not commits:
            return
        self.run(["hg", "update", "-r", revision])
        for commit, message in zip(commits, messages):
            self.run(["hg", "graft", "-q", "-r", commit])
            self.run(["hg", "commit", "--amend", "-m", message])
        self.run(["hg", "strip", "--no-backup", "-r", commits[0]])
        assert len(self.commits_since(revision)) == len(messages), "Expected %s commits after rewording, found %s" % (len(messages), len(self.commits_since(revision)))

    @logEntryExit
    def strip_commits_since(self, revision):
        commits = self.commits_since(revision)
        if commits:
            self.run(["hg", "update", "-C", "-r", revision])
            self.run(["hg", "strip", "--no-backup", "-r", commits[0]])
        assert self.current_revision() == revision, "Stripping the commits since %s left the checkout at %s" % (revision, self.current_revision())

    @logEntryExit
    def discard_working_directory(self):
        # Discards the uncommitted changes, keeping the commits.
        self.run(["hg", "revert", "--all", "--no-backup"])
        self.run(["hg", "purge", "."])

    @logEntryExit
    def changed_files_in(self, directory, since):
        # Files under directory that differ between the revision since and the working
        # directory (including untracked ones), with paths relative to the root of the
        # checkout.
        files = self.run(["hg", "--config", "ui.relative-paths=no", "status", "--no-status", "--rev", since, directory]).stdout.splitlines()
        return [f for f in files if f]

    @logEntryExit
    def diff_stats(self, since):
        ret = self.run(["hg", "diff", "--stat", "-r", since])
        return ret.stdout.rstrip()
