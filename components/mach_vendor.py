# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import logEntryExit, run_command

@logEntryExit
def check_for_update(library):
	return "<new version>"
	# run_command(["./mach", "vendor", "--check-for-update", library.shortname])

@logEntryExit
def vendor(library):
	run_command(["./mach", "vendor", library.shortname])