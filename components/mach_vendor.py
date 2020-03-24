# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit

@logEntryExit
def check_for_update(library):
	run(["./mach", "vendor", "--check-for-update", library.shortname])

@logEntryExit
def vendor(library):
	run(["./mach", "vendor", library.shortname])