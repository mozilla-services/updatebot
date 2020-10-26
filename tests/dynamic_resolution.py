#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import inspect
import unittest

# Test to help me build the logger inheritance structure and ensure it still works.


class Base:
    def __init__(self, loggers):
        self.loggers = loggers

        for i in ["log", "log_exception"]:
            self.__dict__.update({i: self.call_method})

    def call_method(self, *args):
        for logger in self.loggers:
            print(logger, inspect.currentframe().f_code.co_name, *args)


class Sub1(Base):
    def __init__(self):
        pass

    def log(self, message):
        self.received = message

    def log_exception(self, e):
        pass


class Sub2(Base):
    def __init__(self):
        pass

    def log(self, message):
        self.received = message

    def log_exception(self, e):
        pass


class TestCommandRunner(unittest.TestCase):
    def testResolution(self):
        expected_string = "Hello"
        s1 = Sub1()
        s2 = Sub2()
        o = Base([s1, s2])
        o.log(expected_string)

        self.assertEqual(
            s1.received, expected_string, "Did not call Sub1.log correctly"
        )
        self.assertEqual(
            s2.received, expected_string, "Did not call Sub2.log correctly"
        )


if __name__ == "__main__":
    unittest.main()
