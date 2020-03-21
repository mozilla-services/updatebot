#!/usr/bin/env python3

from utilities import Struct

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
	def __init__(self, database_config):
		self.connection = pymysql.connect(
			host=database_config['host'],
			user=database_config['user'],
			password=database_config['password'],
			db=database_config['database'],
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