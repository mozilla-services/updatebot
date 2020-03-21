from components.utilities import logEntryExit

@logEntryExit
def commit(library, bug_id, new_release_version):
	run(["hg", "commit", "-m", "Bug %s - Update %s to %s" % (bug_id, library.shortname, new_release_version)])