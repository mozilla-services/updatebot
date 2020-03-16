#!/usr/bin/env python3



class logEntryExit(object):
	def __init__(self, f):
		self.f = f

	def __call__(self, *args):
		print("================================================")
		print("Beginning", self.f.__name__)
		ret = self.f(*args)
		print("Ending", self.f.__name__)
		return ret


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