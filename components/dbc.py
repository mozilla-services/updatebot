#!/usr/bin/env python3

from components.db import HardcodedDatabase, MySQLDatabase


class Database:
	def __init__(self, database_config):
		self.db = MySQLDatabase(database_config)

	def get_libraries(self):
		return self.db.get_libraries()