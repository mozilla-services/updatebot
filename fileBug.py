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

def fileBug(product, component, summary, description):
	data = {
		'version': "unspecified",
		'op_sys': "unspecified",

		'product': product,
		'component': component,
		'type' : "enhancement",
		'summary': summary,
		'description': description,
		'whiteboard': kw('filed'),
		'cc' : ['tom@mozilla.com']
	}

	r = requests.post(BUGZILLA_URL + "bug?api_key=" + APIKEY, json=data)
	j = json.loads(r.text)
	if 'id' in j:
		return j['id']

	raise Exception(j)

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='File a bug on bugzilla')
	parser.add_argument('--summary', '--subject', '-s', required=True, help='Subject')
	parser.add_argument('--description', '-d', required=True, help='Description')
	parser.add_argument('--product', '-p', required=True, help='Product')
	parser.add_argument('--component', '-c', required=True, help='Component')
	args = parser.parse_args(sys.argv[1:])

	if not APIKEY:
		eprint("API Key not defined in apikey.py")
		eprint("Fill that in with an API Key able to access security bugs.")
		sys.exit(1)

	bugid = fileBug(args.product, args.component, args.summary, args.description)
	print(bugid)
