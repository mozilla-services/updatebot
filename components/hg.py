# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

from components.logging import logEntryExit
from components.providerbase import BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


def reset_repository(cmdrunner):
    cmdrunner.run(["hg", "checkout", "-C", "."])
    cmdrunner.run(["hg", "purge", "."])

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
        self.run(["hg", "commit", "-m", "%s - Apply mozilla patches for %s" %
                  (bug_id, library.name)])

    @logEntryExit
    def diff_stats(self):
        ret = self.run(["hg", "diff", "--stat"])
        return ret.stdout.decode().rstrip()
