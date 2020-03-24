# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit

@logEntryExit
def commit(library, bug_id, new_release_version):
	run(["hg", "commit", "-m", "Bug %s - Update %s to %s" % (bug_id, library.shortname, new_release_version)])