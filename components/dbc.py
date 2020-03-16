#!/usr/bin/env python3

from db import HardcodedDatabase


class Database:
	def __init__(self):
		self.db = HardcodedDatabase()