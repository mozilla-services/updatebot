#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.dbc import Database
from components.mach_vendor import check_for_update, vendor
from components.bugzilla import file_bug, comment_on_bug
from components.hg import commit
from apis.taskcluster import submit_to_try

class Updatebot:
	def __init__(self, database_config):
		self.db = Database(database_config)

	def run(self):
		libraries = self.db.get_libraries()
		for l in libraries:
			try:
				self.process_library(l)
			except Exception as e:
				print(e)
				pass
				# Output some information here....


	def process_library(self, library):
		new_version = check_for_update(library)
		if not new_version:
			return
		if self.db.have_job(library, new_version):
			self.process_existing_job(library, new_version)
		else:
			self.process_new_job(library, new_version)

	def process_new_job(self, library, new_version):
		vendor(library)
		bug_id = file_bug(library, new_release_version)
		commit(library, bug_id, new_release_version)
		try_run = submit_to_try(library)
		comment_on_bug(bug_id, try_run)
		self.db.save_job(library, new_version, bug_id, try_run)

	def process_existing_job(library, new_version):
		pass


def run(database_config=None):
	u = Updatebot(database_config)
	u.run()

if __name__ == "__main__":
	run()