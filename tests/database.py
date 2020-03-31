#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
sys.path.append("..")
import unittest

from components.dbc import Database
from components.db import LIBRARIES
try:
	from localconfig import database_config
except:
	print("Unit tests require a local database configuration to be defined.")
	sys.exit(1)

class TestDatabaseCreation(unittest.TestCase):
	pass
	# Commented out to avoid the test harness from deleting your database.
	#def test_creation_deletion(self):
	#	db = Database(database_config)
	#	db.check_database()
	#	db.delete_database()

class TestDatabaeQueries(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.db = Database(database_config)
		cls.db.check_database()

	def testLibraries(self):
		libs = self.db.get_libraries()

		def check_list(list_a, list_b, list_name):
			for a in list_a:
				try:
					b = next(x for x in list_b if x.shortname == a.shortname)
					for prop in dir(a):
						if not prop.startswith("__") and prop != "id":
							try:
								self.assertTrue(getattr(b, prop), getattr(a, prop))
							except AttributeError as e:
								self.assertTrue(False, "The attribute {0} was not found on the {1} list's object".format(prop, list_name))
				except StopIteration as e:
					self.assertTrue(False, "{0} was not found in the {1} list of libraries".format((a.shortname, list_name)))

		check_list(libs, LIBRARIES, "original")
		check_list(LIBRARIES, libs, "database's")



if __name__ == '__main__':
    unittest.main()
