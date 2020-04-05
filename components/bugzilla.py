#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import json
import argparse
import requests

from apis.bugzilla_api import fileBug, commentOnBug
from components.utilities import logEntryExit

@logEntryExit
def file_bug(library, new_release_version):
	summary = "Update %s to new version %s" % (library.shortname, new_release_version)
	description = ""

	bugID = fileBug(library.bugzilla_product, library.bugzilla_component, summary, description)
	print("Filed Bug with ID", bugID)
	return bugID

@logEntryExit
def comment_on_bug(bug_id, try_run):
	comment = "I've submitted a try run for this commit: " + try_run
	commentID = commentOnBug(bug_id, comment)
	print("Filed Comment with ID %s on Bug %s" % (commentID, bug_id))

