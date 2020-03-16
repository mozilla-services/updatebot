#!/usr/bin/env python3

from utilities import Struct

class HardcodedDatabase:
	def __init__(self):
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