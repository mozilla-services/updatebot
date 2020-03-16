@logEntryExit
def check_for_update(library):
	run(["./mach", "vendor", "--check-for-update", library.shortname])

@logEntryExit
def vendor(library):
	run(["./mach", "vendor", library.shortname])