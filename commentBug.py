#!/usr/bin/env python3

import sys
import json
import argparse
import requests

try:
	from apikey import BUGZILLA_URL, APIKEY
except:
	APIKEY = None

def sq(s):
	return '[' + s + ']'
def kw(s):
	return sq('3pl-' + s)

def commentOnBug(bugID, comment):
	data = {
		'comment': comment
	}

	r = requests.post(BUGZILLA_URL + "bug/" + str(bugID) + "/comment?api_key=" + APIKEY, json=data)
	j = json.loads(r.text)
	if 'id' in j:
		return j['id']

	raise Exception(j)

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Comment on a bug on bugzilla')
	parser.add_argument('--bug', '-b', required=True, help='Bug')
	parser.add_argument('--comment', '-c', required=True, help='Comment')
	args = parser.parse_args(sys.argv[1:])

	if not APIKEY:
		eprint("API Key not defined in apikey.py")
		eprint("Fill that in with an API Key able to access security bugs.")
		sys.exit(1)

	commentid = commentOnBug(args.bug, args.comment)
	print(commentid)