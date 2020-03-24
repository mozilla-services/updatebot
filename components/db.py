#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.utilities import Struct, logEntryExit

import pymysql

class HardcodedDatabase:
	def __init__(self, database_config):
		self.libraries = [
			Struct(**{
				'shortname': 'dav1d',
				'product' : 'Core',
				'component' : 'ImageLib',
				'fuzzy_query' : "'test 'gtest | 'media !'asan"
			})
		]

	def get_libraries(self):
		return self.libraries

class MySQLDatabase:
	@logEntryExit
	def __init__(self, database_config):
		self.connection = pymysql.connect(
			host=database_config['host'],
			user=database_config['user'],
			password=database_config['password'],
			db=database_config['db'],
			charset='utf8',
			cursorclass=pymysql.cursors.DictCursor)

		self.libraries = [
			Struct(**{
				'shortname': 'dav1d',
				'product' : 'Core',
				'component' : 'ImageLib',
				'fuzzy_query' : "'test 'gtest | 'media !'asan"
			})
		]

	def get_libraries(self):
		return self.libraries