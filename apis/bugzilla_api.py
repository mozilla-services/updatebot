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

def commentOnBug(bugID, comment):
	data = {
		'comment': comment
	}

	r = requests.post(BUGZILLA_URL + "bug/" + str(bugID) + "/comment?api_key=" + APIKEY, json=data)
	j = json.loads(r.text)
	if 'id' in j:
		return j['id']

	raise Exception(j)