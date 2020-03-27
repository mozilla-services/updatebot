#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import time
import subprocess

def logEntryExit(func):
	def func_wrapper(*args, **kwargs):
		print("================================================")
		print("Beginning", func.__qualname__)
		ret = func(*args, **kwargs)
		print("Ending", func.__qualname__)
		return ret
	return func_wrapper


class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)


def run_command(args, shell=False, clean_return=True):
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