# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit, BaseProvider, INeedsCommandProvider, INeedsLoggingProvider


class DefaultMercurialProvider(BaseProvider, INeedsCommandProvider, INeedsLoggingProvider):
    def __init__(self, config):
        pass

    @logEntryExit
    def commit(self, library, bug_id, new_release_version):
        bug_id = "Bug {0}".format(bug_id)
        self.run(["hg", "commit", "-m", "%s - Update %s to %s" %
                  (bug_id, library.shortname, new_release_version)])
