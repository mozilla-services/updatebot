#!/usr/bin/env python3

import os
import sys
import time
import inspect
import argparse
import traceback
import subprocess

from components.utilities import logEntryExit, run_command

@logEntryExit
def _vcs_setup():
	if not _vcs_setup.initialized:
		run_command(["./mach", "vcs-setup", "--update"])
		_vcs_setup.initialized = True
_vcs_setup.initialized = False

@logEntryExit
def submit_to_try(library):
	_vcs_setup()
	ret = run_command(["./mach", "try", "fuzzy", "--query", library.fuzzy_query])
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