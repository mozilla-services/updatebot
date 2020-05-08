# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit, INeedsCommandProvider


class DefaultMercurialProvider(INeedsCommandProvider):
    def __init__(self, config):
        super().__init__(config)

    @logEntryExit
    def commit(self, library, bug_id, new_release_version):
        bug_id = "Bug {0}".format(bug_id)
        self.run(["hg", "commit", "-m", "%s - Update %s to %s" %
                     (bug_id, library.shortname, new_release_version)])
