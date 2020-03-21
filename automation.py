#!/usr/bin/env python3

from components.dbc import Database
from components.mach_vendor import check_for_update, vendor
from components.bugzilla import file_bug, comment_on_bug
from component.hg import commit
from apis.taskcluster import submit_to_try

class Updatebot:
	def __init__(self, database_config):
		self.db = Database(database_config)

	def run(self):
		libraries = self.db.get_libraries():
		for l in libraries:
			try:
				self.process_library(l)
			except:
				pass
				# Output some information here....


	def process_library(library):
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

