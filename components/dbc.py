#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.db import HardcodedDatabase, MySQLDatabase


class Database:
	def __init__(self, database_config):
		self.db = MySQLDatabase(database_config)

	def check_database(self):
		return self.db.check_database()

	def get_libraries(self):
		return self.db.get_libraries()

	def get_job(self, library, new_version):
		return self.db.get_job(library, new_version)

	def save_job(self, library, new_version, bug_id, try_run):
		return self.db.save_job(library, new_version, bug_id, try_run)
