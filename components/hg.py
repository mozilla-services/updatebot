# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider

# Shelve is part of Mercurial but not enabled by default.
HG_SHELVE = ["hg", "--config", "extensions.shelve="]
# The shelf the spurious-update check saves the working directory in.
SPURIOUS_CHECK_SHELF = "updatebot-spurious-check"


def reset_repository(cmdrunner):
    cmdrunner.run(["hg", "checkout", "-C", "."])
    cmdrunner.run(["hg", "purge", "."])
    # Drop the shelf if a run was interrupted partway through the spurious-update
    # check. Only ours: the checkout may have other shelves. It's usually not there.
    cmdrunner.run(HG_SHELVE + ["shelve", "--delete", SPURIOUS_CHECK_SHELF], clean_return=False)

    original_revision = os.environ.get("GECKO_HEAD_REV", "")
    if original_revision:
        ret = cmdrunner.run(["hg", "update", original_revision])
    else:
        ret = cmdrunner.run(["hg", "strip", "roots(outgoing())", "--no-backup"], clean_return=False)
        if ret.returncode == 255:
            if "abort: empty revision set" not in ret.stderr.decode():
                ret.check_returncode()


class MercurialProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def commit(self, library, bug_id, new_release_version):
        # Note that this commit message format changes, one must also edit the
        # Updatebot Verify job in mozilla-central ( verify-updatebot.py )
        bug_id = "Bug {0}".format(bug_id)
        self.run(["hg", "commit", "-m", "%s - Update %s to %s" %
                  (bug_id, library.name, new_release_version)])

    @logEntryExit
    def commit_patches(self, library, bug_id, new_release_version):
        # Note that this commit message format changes, one must also edit the
        # Updatebot Verify job in mozilla-central ( verify-updatebot.py )
        bug_id = "Bug {0}".format(bug_id)
        # `./mach vendor --patch-mode only` doesn't register files the patches add or
        # delete (only a full vendor does), so do that here or they'd be left out.
        self.run(["hg", "addremove", "-q", library.vendor_directory, os.path.dirname(library.yaml_path)])
        self.run(["hg", "commit", "-m", "%s - Apply mozilla patches for %s" %
                  (bug_id, library.name)])

    @logEntryExit
    def save_working_directory(self, name):
        # Saves the uncommitted changes (including added, removed and untracked
        # files) without changing the working directory.
        self.run(HG_SHELVE + ["shelve", "--keep", "--unknown", "--name", name])

    @logEntryExit
    def restore_working_directory(self, name):
        # Discards the uncommitted changes and puts back the ones saved as name.
        self.run(["hg", "revert", "--all", "--no-backup"])
        self.run(["hg", "purge", "."])
        self.run(HG_SHELVE + ["unshelve", "--name", name])

    @logEntryExit
    def forget_saved_working_directory(self, name):
        self.run(HG_SHELVE + ["shelve", "--delete", name])

    @logEntryExit
    def changed_files(self, exclude=()):
        # Files that differ from the working directory's parent, counting new and
        # deleted files, with paths relative to the root of the checkout.
        self.run(["hg", "addremove", "-q"])
        excluded = set(os.path.normpath(p) for p in exclude)
        files = self.run(["hg", "--config", "ui.relative-paths=no", "status", "--no-status"]).stdout.decode().splitlines()
        return [f for f in files if f and os.path.normpath(f) not in excluded]

    @logEntryExit
    def diff_stats(self):
        ret = self.run(["hg", "diff", "--stat"])
        return ret.stdout.decode().rstrip()
