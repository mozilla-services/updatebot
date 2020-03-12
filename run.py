#!/usr/bin/env python3

import os
import sys
import argparse

from components import *

#=================================================

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Run it')
	args = parser.parse_args(sys.argv[1:])

	library = "dav1d"

	library = find_library_metadata("dav1d")

	clone()

	vendor(library)

	new_release_version = find_release_version(library)
	if not new_release_version:
		print("Could not find a new release version string")
		sys.exit(0)

	bug_id = file_bug(library, new_release_version)

	commit(library, bug_id, new_release_version)

	try_run = submit_to_try(library)

	commentOnBug(bug_id, try_run)