#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from components.db import HardcodedDatabase, MySQLDatabase


class Database:
	def __init__(self, database_config):
		self.db = MySQLDatabase(database_config)

	def get_libraries(self):
		return self.db.get_libraries()