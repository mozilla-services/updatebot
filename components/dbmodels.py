#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

class JOBSTATUS:
	COULD_NOT_UPDATE = 1
	SUBMITTED_TRY = 1

class Job:
	def __init__(self, row):
		self.id = row['id']
		self.library = row['library']
		self.version = row['version']
		self.status = row['status']
		self.bugzilla_id = row['bugzilla_id']
		self.try_revision = row['try_revision']

class Library:
	def __init__(self, row):
		self.id = row['id']
		self.shortname = row['shortname']
		self.bugzilla_product = row['bugzilla_product']
		self.bugzilla_component = row['bugzilla_component']
		self.fuzzy_query = row['fuzzy_query']
