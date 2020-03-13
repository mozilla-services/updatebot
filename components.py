#!/usr/bin/env python3

import os
import sys
import time
import inspect
import argparse
import traceback
import subprocess

import fileBug
import commentBug

#=================================================

class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)

#----------------

class logEntryExit(object):
	def __init__(self, f):
		self.f = f

	def __call__(self, *args):
		print("================================================")
		print("Beginning", self.f.__name__)
		ret = self.f(*args)
		print("Ending", self.f.__name__)
		return ret

#----------------

def run(args, shell=False, clean_return=True):
	print("----------------------------------------------")
	start = time.time()
	print("Running", args)
	ret = subprocess.run(args, shell=shell, capture_output=True, timeout=60*10)
	print("Return:", ret.returncode, "Runtime (s):", int(time.time() - start))
	print("-------")
	print("stdout:")
	print(ret.stdout.decode())
	print("-------")
	print("stderr:")
	print(ret.stderr.decode())
	print("----------------------------------------------")
	if clean_return:
		if ret.returncode:
			print("Expected a clean process return but got:", ret.returncode)
			print("   (", *args, ")")
			print("Exiting application...")
			ret.check_returncode()
			sys.exit(1)
	return ret

#=================================================

@logEntryExit
def find_library_metadata(library_name):
	return Struct(**{
		'shortname': library_name,
		'find_release_string' : "hg diff media/libdav1d/moz.yaml | grep -E '^\+ ' | cut -d \" \" -f 5-",
		'product' : 'Core',
		'component' : 'ImageLib',
		'fuzzy_query' : "'test 'gtest | 'media !'asan"
	})

#----------------

@logEntryExit
def clone():
	run(["hg", "robustcheckout", "--sharebase", "/tmp/hg-store", "-b", "default", "http://10.0.0.1:7777/", "mozilla-central"])
	os.chdir("mozilla-central")

#----------------

@logEntryExit
def vendor(library):
	run(["./mach", "vendor", library.shortname])

#----------------

@logEntryExit
def find_release_version(library):
	ret = run(library.find_release_string, shell=True)
	return ret.stdout.decode().strip()

#----------------

@logEntryExit
def file_bug(library, new_release_version):
	summary = "Update %s to new version %s" % (library.shortname, new_release_version)
	description = ""

	bugID = fileBug.fileBug(library.product, library.component, summary, description)
	print("Filed Bug with ID", bugID)
	return bugID

#----------------

@logEntryExit
def commit(library, bug_id, new_release_version):
	run(["hg", "commit", "-m", "Bug %s - Update %s to %s" % (bug_id, library.shortname, new_release_version)])

#----------------

@logEntryExit
def _vcs_setup():
	if not _vcs_setup.initialized:
		run(["./mach", "vcs-setup", "--update"])
		_vcs_setup.initialized = True
_vcs_setup.initialized = False

@logEntryExit
def submit_to_try(library):
	_vcs_setup()
	ret = run(["./mach", "try", "fuzzy", "--query", library.fuzzy_query])
	output = ret.stdout.decode()

	isNext = False
	try_link = "Unknown"
	for l in output.split("\n"):
		if isNext:
			try_link = l.replace("remote:", "").strip()
			break
		if "Follow the progress of your build on Treeherder:" in l:
			isNext = True

	return try_link

#----------------

@logEntryExit
def commentOnBug(bug_id, try_run):
	comment = "I've submitted a try run for this commit: " + try_run
	commentID = commentBug.commentOnBug(bug_id, comment)
	print("Filed Comment with ID %s on Bug %s" % (commentID, bug_id))

