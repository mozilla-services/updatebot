#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

class JOBSTATUS:
	COULD_NOT_UPDATE = 1
	SUBMITTED_TRY = 1

JOB_COLUMN_ID 			= 0
JOB_COLUMN_LIBRARY 		= 1
JOB_COLUMN_VERSION 		= 2
JOB_COLUMN_STATUS 		= 3
JOB_COLUMN_BUGZILLA_ID 	= 4
JOB_COLUMN_TRY_REVISION = 5

class Job:
	def __init__(self, row):
		self.id = row[JOB_COLUMN_ID]
		self.library = row[JOB_COLUMN_LIBRARY]
		self.version = row[JOB_COLUMN_VERSION]
		self.status = row[JOB_COLUMN_STATUS]
		self.bugzilla_id = row[JOB_COLUMN_BUGZILLA_ID]
		self.try_revision = row[JOB_COLUMN_TRY_REVISION]